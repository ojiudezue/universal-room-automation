---
name: ura-research-frontier
description: URA research-frontier map — three open problems where URA has a defensible edge beyond commercial hubs and academic SOTA: (1) autonomous energy ROI, (2) learned/predictive home, (3) presence-fusion substrate. Triggers — "what's worth publishing", "where is URA ahead", "next-cycle research topic", "beyond SOTA", "where do we push the frontier", or scoping a multi-cycle research thread instead of a bug fix. No policy overrides — every proposed change still routes through CLAUDE.md tier review.
---

# URA Research Frontier

Purpose: a durable map of where URA could plausibly advance state of the art, grounded in modules that already exist in this repo. This is a **scoping aid, not a plan** — every candidate on this page still has to be filed as a `docs/planning/PLANNING_*.md`, gated through Tier 2 or Tier 2-DB review, and validated live per CLAUDE.md.

**Audience:** you may be a lone Sonnet-class session with no subagent fleet. Every step below is written so one person can execute it sequentially. Fleet usage is an optional accelerator, not a requirement.

**When NOT to use this skill:**
- Cycle-in-flight (planning doc already exists) → use `ura-plan` / `ura-build` skills, not this.
- Live bug or regression → use `homeassistant_coding` + CLAUDE.md Troubleshooting; do not open a research frontier.
- Deploy / release mechanics → `deploy` skill.
- Documentation refresh after a feature landed → `documenter`.
- Retrospective on the current planning conversation → `transition-doc`.

**Non-negotiables (from `CLAUDE.md`, do not weaken here):**
- No Fabrication — cite file:line for every claim; if unverified, mark `candidate` / `open`.
- Institutional Context First — before proposing any new CONF_*/sensor/helper, grep `const.py`, `config_flow.py`, per-platform files, `domain_coordinators/`, `docs/planning/`, and per-coordinator design docs.
- Tier 2-DB (three framing-disjoint reviews) is the **default** for regression-prone changes; strategy/decision-logic changes to the energy or presence stacks are regression-prone by definition.
- Every planning doc needs an "Institutional context verified" section and testable acceptance criteria including a **Live:** bullet.
- README write-back mandate: post-restart live results replace the prospective bullets before the cycle closes.

---

## Frontier map at a glance

| # | Frontier | URA's unique asset (verified) | First measurable win | Tier |
|---|---|---|---|---|
| 1 | Autonomous energy ROI | `energy_battery.py` 3440 LoC arbitrage state machine (WAIT/CHARGE/HOLD/DISCHARGE + ATTAIN), 4-level Optimizer autonomy ladder shipped as constants | Shadow-vs-rule-based $/mo delta over ≥30 days | 2-DB or 3 |
| 2 | Learned / predictive home | `bayesian_predictor.py` 1018 LoC, `routine_forecaster.py` 650 LoC, `regime_detector.py` 620 LoC, `pattern_learning.py` 371 LoC + `parameter_beliefs` DB table | Brier score of next-1h occupancy beating a persistence baseline on a held-out week | 2-DB |
| 3 | Presence-fusion substrate | `OccupancySubstrate` (v4.7.24) + per-room/per-kind `_room_provenance` (v4.7.19) + Tier-1 person-tracker vetoes (v4.7.13/14) + trust-hierarchy | False-vacancy rate on labelled night-time bedroom set below best community fusion baseline | 2 or 2-DB |

Row 1 has the clearest dollar denomination and the biggest blast radius — treat as Tier 3 by default (CLAUDE.md "regression-prone" clause) unless the change is genuinely isolated.

---

## Frontier 1 — Autonomous energy ROI

### The claim
A locally-run, safety-clamped optimizer can beat well-tuned rule-based TOU/battery/EVSE strategies on real dollars, **in a house not a paper**, with a reproducible receipts trail.

### Why current SOTA falls short
- **Commercial hubs** (SPAN, Enphase, Tesla): closed logic, single-vendor scope, no per-house tuning, no auditable receipts. Cannot combine a Tesla battery + non-Tesla EVSE + tariff + weather-conditioned load-shed the way URA does.
- **HEMS academic literature** (see `docs/planning/RESEARCH_2026-05-13_HEMS_optimization_landscape.md` — 77 lines, verify with `wc -l`): MPC/RL papers usually simulate on synthetic loads with no adversarial safety layer, no restart-resilience story, no operator-in-the-loop autonomy ladder.
- **HA community blueprints:** rule-based TOU switching per plug; nobody publishes a multi-coordinator strategy engine with framing-disjoint code review and DB-persisted decision receipts.

### URA's asset today (verified 2026-07-02)
- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — 3440 LoC, arbitrage state machine `WAIT → CHARGE → HOLD → DISCHARGE` with `ATTAIN` catch-up phase (constants at `energy_battery.py:56`, `:67`; see file header lines 7–10).
- Sibling energy coordinators (`energy.py`, `energy_pool.py`, `energy_tou.py`, `energy_forecast.py`, `energy_billing.py`, `energy_circuits.py`) — see `ls custom_components/universal_room_automation/domain_coordinators/energy*.py`.
- **Optimizer autonomy ladder** shipped as constants (`const.py:1561–1601`):
  - `OPTIMIZER_LEVEL_ADVISORY = "advisory"`
  - `OPTIMIZER_LEVEL_SHADOW = "shadow"`  ← current default (`DEFAULT_OPTIMIZER_AUTONOMY_LEVEL`, `const.py:1601`)
  - `OPTIMIZER_LEVEL_PROPOSE_CONFIG = "propose_config"`
  - (numeric priorities `const.py:1579–1582`, plus an ACTUATE level implied by the ladder; verify with `grep -n OPTIMIZER_LEVEL custom_components/universal_room_automation/const.py` before citing).
- **Rolling shadow-accuracy validator** already scaffolded — `OPTIMIZER_SHADOW_ACCURACY_WINDOW_DAYS = 7`, `OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES = 20` (`const.py:1639–1640`); state variables `_shadow_accuracy_samples`, `_last_shadow_accuracy_pct`, `_last_shadow_accuracy_status` on the coordinator (`optimization.py:563–565`).
- **Decision receipts on disk:** DB tables `decision_log` (`database.py:625`), `compliance_log` (`:668`), `outcome_log` (`:844`), `optimization_findings` (`:770`), `optimization_daily_digest` (`:811`), `energy_history` (`:486`, DoW+hour indexed at `:510`), `energy_snapshots` (`:423`). Single-writer asyncio queue at `database.py:45-51` — respect it, don't add second writers.
- **VibeMemo prior-art anchors:** v5.5.0 inclement-weather hold shipped Tier 2-DB; v5.5.3 arbitrage/attain reserve-floor cycle exposed Bug Class #53 (computed-but-not-consumed) and prompted the Tier-3 protocol. The 4th (D) reviewer found `D-HIGH-1` — a leak three converging reviewers missed. Treat that history as your prior on how easy it is to be wrong here.

### Why URA can go further than SOTA
1. **Grounded receipts:** every decision persisted with inputs, outcome, compliance — makes "beat rule-based by $X" a first-class query, not a claim.
2. **Safety-first autonomy ladder:** four discrete tiers so the frontier work runs at Shadow while the house runs on rules; graduation is gated by a rolling accuracy metric that already exists.
3. **Framing-disjoint review process:** Tier 3 with an adversarial-completeness (D) pass is unusual in the community and empirically catches multi-reviewer blind spots (v5.5.3).

### First three concrete steps IN THIS REPO
1. **Baseline the ledger.** Confirm you can answer "for calendar month M, what would the arbitrage state machine have chosen and what did we actually charge for" from `decision_log` + `energy_snapshots` + `energy_history` alone. If you cannot, the missing columns are Cycle 1 — nothing else matters until this query returns. Start from `database.py:486` (`energy_history`) and `:625` (`decision_log`).
2. **Wire the shadow-accuracy sensor to a $ metric.** The optimizer already tracks correctness (`optimization.py:920 _run_shadow_accuracy_validator`). Add a sibling that tracks *dollar delta vs the rule-based path the deployed strategy actually took*. Publish it as a diagnostic sensor next to `sensor.ura_energy_coordinator_battery_strategy`. Institutional-context-first: grep `sensor.py` for existing energy diagnostic sensors before adding.
3. **Publish the "receipts" tooling.** A single `python3 scripts/…` (does not exist yet — new) that emits a monthly savings JSON from the DB. This is the artifact any commercialization play (`docs/planning/COMMERCIALIZATION_options.md` §2 "URA Cloud") depends on. Filing this as an offline read-only script avoids Tier 2-DB risk.

### You have a result when…
> Over a rolling 30-day window with ≥20 shadow samples (existing threshold `OPTIMIZER_SHADOW_ACCURACY_MIN_SAMPLES`), the shadow-recommended action set beats the actually-executed rule-based strategy by **≥ $X and ≥ Y%** in bill impact, on this specific tariff, with 95% CI derived from bootstrapped daily-delta samples, and the calculation is reproducible from `decision_log` + `energy_history` alone.

X and Y are operator-set thresholds — pick them before running the experiment, not after. A negative result (shadow loses to rules) is still a result: it tells you the rule tuning is state-of-the-art here and the next cycle is elsewhere.

### Commercialization link
`docs/planning/COMMERCIALIZATION_options.md` Plays 1 + 2: the "your house saved $X" monthly report is exactly this ledger. Prototype it as a local sensor (Play 2 "first step") before any cloud story. Norm-compatible with Frigate+ / Nabu Casa.

---

## Frontier 2 — Learned / predictive home

### The claim
Bayesian occupancy + routine forecasting + regime detection, learned per-house over months of ground truth, can drive HVAC / lighting / notification decisions **before** the human triggers them, at accuracies not achievable by generic per-room delay heuristics.

### Why current SOTA falls short
- **Commercial:** Nest/Ecosee learn a *thermostat schedule*, not per-room per-hour occupancy priors joined to weather regime.
- **Academic** (see `docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md` — 103 lines): most occupancy-prediction papers stop at accuracy on public datasets; almost none run in a house for a year with a restart-resilience story and a graduation ladder from shadow → actuation.
- **HA community:** template sensors + hand-tuned delays; no one persists posteriors across restarts with an audited learning-status FSM.

### URA's asset today (verified 2026-07-02)
- `custom_components/universal_room_automation/bayesian_predictor.py` — 1018 LoC. Classes: `TimeBin` (`:47`), `LearningStatus` (`:58`), `DataQualityReport` (`:92`), `BayesianPredictor` (`:132`). Explicit learning-status FSM, day-type + time-bin discretization (`_hour_to_time_bin` `:948`, `_day_type` `:964`).
- `domain_coordinators/routine_forecaster.py` — 650 LoC. `RoutineForecaster` (`:117`) with matching `_hour_to_time_bin` (`:68`), `_day_type` (`:83`), `_collapse_vocab` (`:108`). Shared bin logic with the predictor is a load-bearing invariant — do not drift.
- `domain_coordinators/regime_detector.py` — 620 LoC. `_js_divergence` (`:42`), `_magnitude_bucket` (`:75`), `RegimeDetector` (`:86`) — Jensen–Shannon over daily distributions is unusual and worth writing up.
- `pattern_learning.py` — 371 LoC. `PatternLearner` (`:20`).
- **Persistence surface (DB, from `database.py`):** `occupancy_events` (`:393`), `environmental_data` (`:408`), `zone_events` (`:471`), `person_visits` (`:517`), `person_presence_snapshots` (`:537`), `room_transitions` (`:552`), `census_snapshots` (`:586`), `person_entry_exit_events` (`:607`), and the belief store: `parameter_beliefs` (`:865`) + `parameter_history` (`:878`). This is a **months-deep behavioral corpus** commercial hubs cannot replicate.
- `docs/Coordinator/` per-coordinator design docs are the reading list before proposing changes to any of these — required by CLAUDE.md Institutional-Context-First rule.

### Why URA can go further than SOTA
1. **Real ground truth, months deep, single household** — closer to home-scale reality than paper datasets, cheaper to iterate on than fleet studies.
2. **Explicit learning-status FSM + data-quality report** already in the predictor — separates "we don't know yet" from "we know and are wrong", which most published models conflate.
3. **Shadow ladder** applies here too: predict → log → grade → graduate, without ever silently over-driving actuators.

### First three concrete steps IN THIS REPO
1. **Nail the offline evaluation harness.** A read-only script that pulls the last 30 days from `occupancy_events` (or `person_visits`), replays through `BayesianPredictor` in a sandbox instance, and reports per-room Brier score + calibration curve. Start from `bayesian_predictor.py:132` and the `LearningStatus` enum (`:58`). Do NOT touch the live predictor — write the replay path first, verify it recomputes yesterday's known predictions bit-identical, then start comparing variants.
2. **Cross-validate the shared bin/day-type invariant.** Add a unit-level test that asserts `bayesian_predictor._hour_to_time_bin == routine_forecaster._hour_to_time_bin` and same for `_day_type`. Drift here silently breaks joint reasoning. Test lives in `quality/tests/` per the project test convention (`PYTHONPATH=quality python3 -m pytest quality/tests/ -v`).
3. **Publish a "predictive accuracy" diagnostic sensor** (advisory only). Rolling 7-day Brier vs a persistence baseline (baseline = "next hour looks like this hour last week"). Sensor is diagnostic-only until it clears an operator-set threshold — the same shadow-graduation pattern the optimizer uses.

### You have a result when…
> On a held-out week of `occupancy_events` from at least 3 rooms with distinct usage profiles (bedroom, living, low-traffic), URA's Bayesian predictor achieves **Brier score < Z** and **calibration ECE < W** while beating a persistence-baseline predictor by at least ΔBrier ≥ B, with the numbers reproducible from the offline harness and unchanged across a restart.

Z, W, B are operator-set before the experiment. If you cannot pick them because you don't know the baseline yet, running the persistence baseline is Cycle 0.

### Commercialization link
`COMMERCIALIZATION_options.md` Play 2 "URA Cloud → fleet-tuned Bayesian priors" — a shared prior distilled from many houses is only meaningful once the per-house evaluation harness exists. Do the per-house version first.

---

## Frontier 3 — Presence-fusion substrate

The identity/fusion/cameras manual (`docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md`) is the canonical starting point for the cross-modal fusion paper + OSS library work.

### The claim
A per-room / per-kind provenance layer with an explicit trust hierarchy and adversarial vetoes generalises across smart-home stacks and is publishable as a substrate, not just a URA feature.

### Why current SOTA falls short
- **Commercial:** hubs expose "occupied / not occupied" — a single boolean with no provenance. When it's wrong, you can't debug it.
- **Academic** (RESEARCH_2026-06-03…): sensor-fusion papers often assume trusted independent sensors; they do not model *known-noisy* modalities (mmWave that trips on fans, cameras that flicker on IR headlights) with per-modality provenance and explicit trust vetoes.
- **HA community:** best practice is `binary_sensor.group` OR — no provenance, no trust hierarchy, no adversarial audit.

### URA's asset today (verified 2026-07-02)
- **`OccupancySubstrate`** (v4.7.24 shipped) — `domain_coordinators/occupancy_substrate.py:85`, 469 LoC. Per-room / per-kind raw layer beneath both room and zone tiers, sourced from curated CONF sensor lists (single source of truth for discovery + kind classification). Bug Class #50 (v4.7.24 review B-C1) is the load-bearing invariant to preserve: the substrate subscription must survive periodic subscription rebuilds.
- **Per-kind provenance** (v4.7.19) — `presence.py:471 self._room_provenance: Dict[str, Dict[str, bool]]`; `_room_occupied` is now a derived `@property` (`presence.py:527`), truth-preserving OR of provenance. Invariants documented in-file at `presence.py:340–465`:
  1. `_room_occupied[r] == any(_room_provenance[r].values())`
  2. Every kind ∈ `TIER1_KINDS`
  3. Key sets match
- **Trust vetoes** (v4.7.13 sleep-state, v4.7.14 away-state) — sleep-only person-trust gate at `presence.py:1151`; away veto with `unidentified_count == 0` guard so guests still count. Bug Class #48 (Away-state person-tracker veto) is the origin story.
- **Fan-noise mitigation stack** (v4.7.19–22) — silent confidence-discount+decay (Layer 1) → BLE-gated fan pause + recheck (Mode 2, v4.7.22). The state machine that pauses a fan shaking mmWave and rechecks occupancy is the piece worth writing up.
- **Persistence:** `occupancy_events` (`database.py:393`), `zone_events` (`:471`), `person_visits` (`:517`), `person_entry_exit_events` (`:607`), `room_transitions` (`:552`).
- **Live view:** `sensor.<room>_occupancy` and `substrate_kinds` attribute (v4.7.24 live-validation) — visible via `ha_get_state` and MCP `home-assistant.ha_get_entity`.

### Why URA can go further than SOTA
1. **Provenance as a first-class citizen** — not a debug flag, an invariant tested at import via inline audit functions (`presence.py:340`).
2. **Trust hierarchy with adversarial cases baked in** — sleep, away, guest, and mmWave-fan-noise all have explicit branches with production incidents behind them (Bug Classes #48, #50, and the v4.7.19–22 fan saga).
3. **Publishability** — the substrate + provenance + veto pattern is stack-agnostic. It can be described independent of URA and reused wherever noisy multi-sensor rooms need debuggable presence.

### First three concrete steps IN THIS REPO
1. **Lock the invariants as tests.** The four invariants in `presence.py:340–465` are documented and enforced at runtime; port them into `quality/tests/` as pure unit tests over synthetic `_room_provenance` inputs. This is a substrate-integrity guarantee against future drift.
2. **Emit a labelled dataset.** A read-only DB query that joins `occupancy_events` with any human-labelled overrides (e.g. operator-toggled "actually empty" moments) to produce a `(timestamp, room, per-kind provenance, true_state)` CSV. Labelling is Cycle 0 — probably ~1 week of operator effort. Without it, "we beat SOTA" is unfalsifiable.
3. **Baseline a naive fusion** on the same labelled set (e.g. plain OR, or majority vote) so URA's provenance+veto fusion has a real comparator. Publish both curves side-by-side as a diagnostic sensor pair.

### You have a result when…
> On a labelled test set of ≥N room-hours spanning nights (fan-noise regime) and empty-house evenings (away-veto regime), URA's provenance+veto fusion achieves **false-vacancy rate ≤ F** and **false-occupancy rate ≤ G**, strictly Pareto-dominating both the naive OR baseline and a documented community pattern (e.g. HA `binary_sensor.group` + template delay), reproducible from the labelled CSV alone.

N, F, G are operator-set. A community-comparable win is publishable even without huge N — the point is that the fusion pattern is defensible, not that this single house's numbers generalize.

### Commercialization link
Not a direct product; a **substrate that could be white-labelled**. Ties into `COMMERCIALIZATION_options.md` Play 1 (companion app must expose per-kind provenance in a legible UI — the substrate is what makes it possible). Publishability is a separate goal from monetization.

---

## Cross-frontier notes

### Data hygiene (all three frontiers depend on this)
| Table | Purpose | `database.py` line | Consumers |
|---|---|---|---|
| `occupancy_events` | Room-level occupancy log | :393 | Frontiers 2, 3 |
| `environmental_data` | Env sensor history | :408 | Frontier 2 |
| `energy_snapshots` | Per-cycle energy state | :423 | Frontier 1 |
| `external_conditions` | Weather / grid | :452 | Frontiers 1, 2 |
| `zone_events` | Zone occupancy | :471 | Frontiers 2, 3 |
| `energy_history` | Long-form energy w/ DoW+hour idx | :486, idx :510 | Frontier 1 |
| `person_visits` / `person_presence_snapshots` / `room_transitions` | Per-person trajectory | :517 / :537 / :552 | Frontiers 2, 3 |
| `decision_log` / `compliance_log` / `outcome_log` | Decision receipts | :625 / :668 / :844 | Frontier 1 |
| `anomaly_log` | Regime / anomaly evidence | :737 | All (validation) |
| `optimization_findings` / `optimization_daily_digest` | Optimizer output | :770 / :811 | Frontier 1 |
| `metric_baselines` | Baseline snapshots | :829 | All (delta claims) |
| `parameter_beliefs` / `parameter_history` | Belief store | :865 / :878 | Frontier 2 |

Single-writer asyncio queue at `database.py:45–51` — every research addition reads from this DB; do not add a second writer.

### Live-validation & data-source verification
- Live env: HA at `192.168.13.13`. Live config via Samba mount — exact mount command and paths are in `CLAUDE.md` under "Data Source Verification". Copy verbatim from there; do not invent paths.
- MCP surface: `home-assistant.*` (`ha_get_state`, `ha_get_logs`, `ha_get_history`, `ha_get_integration`, `ha_get_entity`), `ura-sqlite` for the URA DB, `unifi`. Use for live-validation and ledger queries.
- Fallback when mount / MCP is down: SSH into HA host and read the DB directly, or use `ha_get_history` against the relevant entities — see the CLAUDE.md Troubleshooting section for the concrete remount command.

### Review tiering (from CLAUDE.md, not overridden here)
| Change shape | Default tier | Framings |
|---|---|---|
| Read-only script that pulls from DB and emits a CSV/JSON | Tier 1 (hotfix) | one adversarial pass |
| New diagnostic sensor (no actuator) | Tier 2 | correctness + async/lifecycle |
| New DAO / migrates callers to a new DAO | Tier 2-DB | A data-integrity / B migration / C new-surfaces |
| Change to arbitrage / attain / reserve floor / trust-hierarchy / shared primitive | Tier 3 | A local / B state-machine / C real-source-mutation test authority / D adversarial completeness |

If in doubt, **elevate**. The v5.5.3 incident is the durable prior: three converging reviewers all shipped a leak the 4th caught.

### Running the reviews yourself (no fleet)

Full lone-session protocol (pre-review tag → framing A/B/C for Tier 2-DB, +D for Tier 3 → per-framing review docs at `docs/reviews/code-review/vX.Y.Z_<name>_review<A|B|C|D>_<framing>.md`) lives in `ura-change-control` §Framing-disjoint reviews (fact-home). Fleet accelerator: dispatch four `ura-reviewer` agents in parallel with explicit different framings. Same output, less clock time.

### VibeMemo prior art to read before proposing anything here
- v5.5.0 inclement-weather hold + v5.5.3 arbitrage-WAIT floor + Bug Class #53 — Frontier 1 landmines.
- v4.7.24 substrate unification + Bug Class #50 (v4.7.19 provenance split, v4.7.20–22 fan-noise stack) — Frontier 3 landmines.
- v5.0.0–v5.2.1 optimizer DB write-flood + rollback — the reason Frontier 1 must batch writes and never emit boot-transient findings.

Recall lines are in `~/.claude/projects/-Users-okosisi-Code-universal-room-automation/memory/MEMORY.md`; body files sit next to it.

---

## Provenance and maintenance

**Every file:line and constant on this page was verified against the repo on 2026-07-02.** Re-verify with the commands below before citing in a planning doc.

| Fact | Re-verify command |
|---|---|
| Coordinator LoC + module list | `wc -l custom_components/universal_room_automation/bayesian_predictor.py custom_components/universal_room_automation/pattern_learning.py custom_components/universal_room_automation/domain_coordinators/{routine_forecaster,regime_detector,optimization,occupancy_substrate,energy_battery,presence}.py` |
| Arbitrage phase constants | `grep -n "ARBITRAGE_PHASE_\|reserve_soc\|effective_reserve" custom_components/universal_room_automation/domain_coordinators/energy_battery.py \| head` |
| Optimizer autonomy ladder | `grep -n "OPTIMIZER_LEVEL_\|DEFAULT_OPTIMIZER_AUTONOMY_LEVEL\|OPTIMIZER_SHADOW_ACCURACY" custom_components/universal_room_automation/const.py` |
| Optimizer shadow-accuracy state | `grep -n "_shadow_accuracy_samples\|_last_shadow_accuracy" custom_components/universal_room_automation/domain_coordinators/optimization.py` |
| DB tables + line numbers | `grep -n "CREATE TABLE\|CREATE INDEX" custom_components/universal_room_automation/database.py` |
| Provenance invariants + class | `grep -n "_room_provenance\|_room_occupied\|OccupancySubstrate" custom_components/universal_room_automation/domain_coordinators/presence.py custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py \| head -30` |
| Person-trust vetoes (sleep + away) | `grep -n "sleep\|all_tracked_persons_away\|unidentified_count" custom_components/universal_room_automation/domain_coordinators/presence.py \| head` |
| Research docs sanity | `wc -l docs/planning/RESEARCH_2026-05-13_HEMS_optimization_landscape.md docs/planning/RESEARCH_2026-06-03_presence_sensor_fusion_noise_prone_environments.md` |
| Commercialization context | `head -40 docs/planning/COMMERCIALIZATION_options.md` |
| Bug-class ledger | `grep -c "^## Bug Class" docs/QUALITY_CONTEXT.md` (header currently stale at 51; body count is truth) |

**Volatile:** module LoC and line numbers drift every cycle. Treat this page as *last-verified 2026-07-02*; re-run the table above before citing a specific line in a new planning doc. Do not amend this skill for every line drift — only when a whole frontier's story changes (e.g. optimizer graduates past L1 Shadow, a new coordinator lands, or a DB table's meaning changes).

**One home per fact:** this skill deliberately does NOT re-explain the review tiers, the deploy pipeline, the mount command, or the No-Fabrication rule. Those live in `CLAUDE.md`. If a claim on this page contradicts CLAUDE.md, CLAUDE.md wins and this skill is the bug.
