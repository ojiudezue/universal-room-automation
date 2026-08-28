---
name: ura-failure-archaeology
description: Chronicle of major URA investigations, dead ends, reverts, and killed features — indexed as symptom → root cause → evidence → status → fence. Load BEFORE any change that could re-fight a settled battle. Triggers — Storm Guard, standalone "comfort coordinator", DB write-flooding, load shedding as a normal cycle, broad regex/sed edits, update-listener reload-on-change, boot-time actuation without settle gate, "monitor for 24h", fan-noise/mmwave-shake, Envoy/SPAN/battery-percentage source, "revert"/"rollback"/"incident"/"crisis"/"broken release". Also load for planning that maps to Bug Class #34/#46/#48/#49/#50/#51/#52/#53.
---

# URA Failure Archaeology

## Memory first — MANDATORY entry point (operator-coined 2026-08-14)

Before mining the recorder, HA logs, or raw URA DB tables for ANY investigation or
trace: **query the hierarchical memory facade first.** The house has been journaling
adjudicated episodes since v5.47.0 (`memory_episodes`: exterior_track,
actuation_conflict, occupancy_phantom, fan_transition_suppressed, comfort_fan_vetoed
— 1,799 rows as of 2026-08-14) and the `universal_room_automation.memory_query`
service exposes `episodes` / `narrative` / `unusual` / `profile` / `facts` verbs per
node (room / zone / house / coordinator).

- Start: `memory_query` `narrative` for the affected node + window, then `episodes`
  filtered by type, then `unusual` for z-scored oddities.
- Raw recorder/DB mining is the **verify** step, not the entry point — memory
  narrows the window and names the mechanism candidates first.
- If memory has NO coverage for the question, say so explicitly in the
  investigation doc — each gap is a candidate episode-type writer (card it).

Why: investigations (e.g. AWAY-BLOCK-1 2026-08-13) hand-mined 4-hour recorder
traces while adjudicated episodes covering the same mechanisms sat unconsulted.


The chronicle of URA's expensive lessons. Every entry is a battle already fought. Read the matching entry BEFORE proposing a fix, so you do not re-fight it.

**Format for every incident:** Symptom → Root cause → Evidence (file:line, commit, doc) → Status → Fence (the wrong paths that were tried and rejected, and why not to try them again).

**All facts date-stamped `verified 2026-07-02` were re-verified this session against the live repo. Anything without that stamp is inherited from an incident memo and should be re-confirmed if you're about to make a load-bearing decision on it.**

**When NOT to use this skill:**
- Greenfield feature that has no analogue in the archive → skip; go read `docs/planning/` + `docs/Coordinator/` instead.
- Pure doc / dashboard edits with no code impact → skip.
- Deployment mechanics → use the `deploy` skill.
- Test authoring → use `homeassistant_coding` + read `quality/tests/conftest.py`.

**Reading order for a "why can't we just..." moment:**
1. Chronological index below — find the version / feature name.
2. Jump to the detail section.
3. Read the **Fence** row. Do not skip it.
4. If the operator or another agent is pushing the fenced path, cite the entry back.

---

## Chronological index

| Date | Version(s) | Incident / decision | Class | Where |
|---|---|---|---|---|
| 2025-11-23 | v2.3.0 → v2.3.3 | Regression cascade from broad regex "fix" | Rushed edit, no syntax gate | [§1](#1-v23x-regression-cascade-2025-11-23) |
| 2026-02-24 | v3.4.0 → v3.4.4 | Camera Census strings/translations/deploy-script gap | Config/tooling | [§2](#2-v34x-camera-census-strings--deploy-staging-gap-2026-02-24) |
| 2026-03-ish | v3.18.1 → v3.22.6 | "database is locked" crisis + thread-safety cascade | DB concurrency | [§3](#3-v318x--v322x-db-lock-crisis-and-thread-safety-cascade) |
| 2026-03-ish | v3.18.7 | Config-flow save error — update-listener revert | Config-flow bootstrap re-entrancy | [§4](#4-v3187-update-listener-revert-config-flow-save-error) |
| 2026-05-29 | v4.7.4 → v4.7.4.4 | Broken release: bootstrap re-entrancy + dead import + unresolved merge markers | Pre-deploy gate missing | [§5](#5-v474--v4744-broken-release-cascade-2026-05-29) |
| 2026-05-30 | v4.7.13 / v4.7.14 | Sleep- and Away-state person-tracker trust — added, not the same | Presence tier omission | [§6](#6-sleep--away-state-trust-cycles-v4713--v4714) |
| 2026-06-02 | v4.7.16.3 → v4.7.16.5 | DPM baseline silently returning None since v4.7.3 | Bug Class #49 | [§7](#7-dpm-baseline-silent-none-v47163--v47165) |
| 2026-06-03 | v4.7.18.1 | Sleep→Waking deadlock hotfix | State-machine wake path | [§8](#8-sleepwaking-deadlock-v47181) |
| 2026-06-03 → 06-05 | v4.7.19 → v4.7.22 | Fan-noise / mmwave-shake saga | Presence fusion | [§9](#9-fan-noise--mmwave-shake-saga-v4719--v4722) |
| 2026-06-03 | (not URA) | "Study B thermostat oscillation" — Better Thermostat, exonerated | Diagnosis, not fix | [§10](#10-study-b-thermostat-oscillation--not-ura-2026-06-03) |
| 2026-06-03 | (feedback) | Parent-entry reload → watchdog restart | Reload discipline | [§11](#11-parent-entry-reload--watchdog-restart-hazard-2026-06-03) |
| 2026-06-04 | v4.7.20.1 | UnboundLocalError from conditional import (Bug Class #34 recurrence) | Import scope | [§12](#12-v47201-conditional-import-unboundlocalerror-bug-class-34) |
| 2026-06-04/05 | v4.7.21 | Cold-boot away-actuation storm settle gates | Boot storm | [§13](#13-cold-boot-away-actuation-storm--v4721-settle-gates) |
| 2026-06-08 → 06-12 | (decision) | Load Shedding pulled from normal cycle queue | Feature framing | [§14](#14-load-shedding-pulled-from-queue-2026-06-08--2026-06-12) |
| 2026-06-09 | v5.0.0 → v5.2.1 | **Optimizer DB write-flood → same-day ROLLBACK** to v4.7.33 | Write-queue saturation | [§15](#15-optimizer-write-flood--same-day-rollback-v500v521-2026-06-09) |
| 2026-06-12 | (incident) | Envoy boot incident: after_dependencies stranding + RestoreEntity unavailable→OFF poisoning | Boot ordering + restore semantics | [§16](#16-envoy-boot-incident--v537-fix-2026-06-12) |
| 2026-06-15 | v5.5.0 | **Storm Guard REPLACED** by local inclement-fusion | Feature swap | [§17](#17-storm-guard--inclement-fusion-v550-2026-06-15) |
| 2026-06-16 | (directive) | **Battery SOC source = Envoy, NOT SPAN** | Data source discipline | [§18](#18-battery-soc--envoy-not-span-2026-06-16) |
| 2026-06-07 | (decision) | **Comfort coordinator KILLED**, sliders folded into Optimization Coordinator | Feature framing | [§19](#19-comfort-coordinator-killed-2026-06-07) |
| 2026-06-16 | v5.5.3 | Tier-3 4th-reviewer D-HIGH-1 leak — arbitrage-attain floor gap | Adversarial completeness | [§20](#20-v553-tier-3-d-high-1-latent-leak-2026-06-16) |

---

## 1. v2.3.x regression cascade (2025-11-23)

**Source:** `quality/POST_MORTEM_v2_3_1-2-3.md` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | `AttributeError: 'NoneType' object has no attribute 'get'` in sensor.py after v2.3.0 exposed a latent startup race; three hotfixes (v2.3.1, v2.3.2, v2.3.3) required to recover. |
| Root cause | v2.3.1 used a broad regex to add None checks across entire files. The regex matched class-definition lines and produced syntax like `class HumiditySensor(UniversalRoomEntity, SensorEntity) if self.coordinator.data else SensorEntity:`. No syntax validation ran before deploy. |
| Evidence | `POST_MORTEM_v2_3_1-2-3.md:56–79` — the exact regex + broken output. |
| Status | Closed. Codified into the pre-deploy gate. |
| **Fence** | Do NOT reach for a repo-wide regex/sed to "fix None handling" (or any structural Python concern). Prefer targeted edits per call-site, or a helper. Any bulk edit MUST run `py_compile` on every changed file before commit — see the **Pre-Deploy Zero-Bugs Gate** memo. |

---

## 2. v3.4.x Camera Census strings + deploy staging gap (2026-02-24)

**Source:** `quality/POST_MORTEM_v3_4_0.md` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | UI showed raw config keys; strings fix committed locally but never shipped; entity selector exposed all binary sensors on camera device, not just person detection. |
| Root cause | (a) `strings.json` and `translations/en.json` not part of the pre-review checklist. (b) `deploy.sh` only staged `*.py` and `manifest.json` — JSON, translations, tests silently dropped. (c) Selector used `domain="binary_sensor"` instead of `domain="camera"` with device-registry resolution. |
| Evidence | `POST_MORTEM_v3_4_0.md:22–41`. |
| Status | Closed at v3.4.4. `deploy.sh` now stages `*.json`, `translations/`, `quality/tests/`. |
| **Fence** | When adding a config-flow field: strings.json AND translations/en.json required, verified BEFORE deploy. Do NOT assume `deploy.sh` picks up new file types — check `scripts/deploy.sh` staging list explicitly. When selecting camera-adjacent entities, select the `camera` domain and resolve companions via device registry — not `binary_sensor`. |

**Consolidated camera history:** Frigate-1 retirement / ghost-detection evidence chain and the Protect Alarm Manager webhook status are consolidated in `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` §1.1, §1.3, §2.3.

---

## 3. v3.18.x – v3.22.x DB-lock crisis and thread-safety cascade

**Source:** git log grep `v3.18|v3.19|v3.22` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | "database is locked" errors, energy jitter, sensor log spam, ~2310 HA thread-safety violations from signal handlers. |
| Root cause | Multiple writers to the URA sqlite DB without serialization; signal handlers scheduled state writes from wrong threads. |
| Evidence | Commits `485fd4f6` v3.18.1 (@callback on 15 signal handlers), `8c1544e6` v3.18.4 ("Fix DB locked, energy jitter, sensor log spam"), `94ba3f90` v3.19.1 (override thread-safety + diagnostics DB lock), `ee26b157` v3.22.5 ("serialize all writes through asyncio.Lock"), `e0924e54` v3.22.6 ("read/write path separation + monitoring"). Current invariant: single-writer asyncio queue at `custom_components/universal_room_automation/database.py:45-51`. |
| Status | Closed at v3.22.6. Single-writer queue is the invariant since. Later re-tripped in a different form → see §15. |
| **Fence** | Do NOT introduce a second DB writer path. All DB writes go through the single asyncio queue in `database.py`. Do NOT call sync sqlite from a signal handler; all handlers must be `@callback` and dispatch through the queue. If you catch yourself writing "just one direct write is fine" — stop, read §15, then find the queue. |

---

## 4. v3.18.7 update-listener revert (config-flow save error)

**Source:** commit `4c889a38` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | Config-flow "save" produced an error when the update listener tried to selectively reload. |
| Root cause | An attempted optimization made the update listener reload only some entries under some conditions. Under the actual entry graph it dropped required reloads and errored. |
| Evidence | Commit message: "Fix config flow save error — revert update listener to always reload". |
| Status | Reverted; policy is **update listener always reloads** for URA config entries. |
| **Fence** | Do NOT add per-field conditional reload logic in the update listener. If you think a reload is too expensive, look at the CM reload-suppression cycle stack (v4.7.26 + v4.7.27) — the fix is to suppress no-op reloads at write time, not to fork the listener. |

---

## 5. v4.7.4 → v4.7.4.4 broken-release cascade (2026-05-29)

**Source:** git log grep `v4.7.4` (verified 2026-07-02) + memo `feedback_pre_deploy_zero_bugs_gate`.

| Field | |
|---|---|
| Symptom | v4.7.4 shipped; v4.7.4.1 needed for `async_update_entry` bootstrap re-entrancy; v4.7.4.2 for a dead import that broke HA 2026.5.4 form open; v4.7.4.3 shipped with unresolved merge conflict markers → SyntaxError → v4.7.4.4 to actually apply it. |
| Root cause | (a) A `customize_buckets` migration called `async_update_entry` mid-bootstrap → re-entrancy → stage-2 timeout on cold install. (b) A dead import was retained and only broke against a newer HA core. (c) Merge conflict markers made it to master; source-grep AST tests didn't catch it. |
| Evidence | Commits `6419b934` (4.7.4.1 hotfix), `1552fa12` (4.7.4.2 URGENT), `8f5d5d15`→`c17fc9fd`→`aeeef777`→`cd9efd6b` (the 4.7.4.3/4.7.4.4 mess). |
| Status | Closed. Produced the **Pre-Deploy Zero-Bugs Gate** rule. |
| **Fence** | Before every `deploy.sh`: (1) `grep -rn '<<<<<<<\|=======\|>>>>>>>' custom_components/universal_room_automation/` returns nothing; (2) `python3 -m py_compile` every changed `.py`; (3) cycle tests green; (4) baseline test-count matches `pre-review-vX.Y.Z`. Do NOT skip. Do NOT trust AST-based smoke tests to catch conflict markers or syntax errors — they don't. Do NOT call `hass.config_entries.async_update_entry` from a migration path that runs during entry setup — defer to `async_add_executor_job` or a post-setup callback. |

---

## 6. Sleep- and Away-state trust cycles (v4.7.13 + v4.7.14)

**Source:** git log + MEMORY.md entries (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | Master bedroom fan cycled all night despite occupant in bed (v4.7.13). Empty-house state oscillated home ↔ away every 60–90s (v4.7.14). |
| Root cause | Presence tier ignored person-tracker signal during sleep and away states. Historical AND-gate + away-filter (shipped v3.6.0-c1; former anchors `presence.py:391` / `:1502` have drifted — grep `all_tracked_persons_away` for current params `presence.py:910`/`:912` and away-veto branch `~:980-981`) had never been extended to trust `person.<name> == home` as an override. Environmental shift (camera noise floor up) exposed it. |
| Evidence | Planning docs `PLANNING_v4.7.13_sleep_state_zone_presence_trust.md`, `PLANNING_v4.7.14_away_state_person_tracker_trust.md`. v4.7.14 veto requires `unidentified_count == 0` to preserve guest detection. |
| Status | Both shipped and live. v4.7.14 produced 33-min uninterrupted dwell (vs 60-90s bounce pre-fix). |
| **Fence** | Sleep-state trust and away-state trust are **different code paths** (`StateInferenceEngine.infer()` vs `ZoneAnyoneBinarySensor.is_on`). Do NOT ship one and assume it covers the other. When extending person-trust to a new state (e.g. home_night — see the still-open "zone away when occupied" finding), do it as a sibling patch on the specific state's path, not a global change. |

---

## 7. DPM baseline silent None (v4.7.16.3 → v4.7.16.5)

**Source:** commits `4e5ec661`, `41a09721`, `0c63194e` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | DPM feature silently non-functional; every tick returned None baseline. Also `EnergyImportTodaySensor` had wrong `state_class`. |
| Root cause | The v4.7.3 DPM refactor removed the baseline derivation but left the calling shape intact. No sensor exposed the failure loudly (Bug Class #49 — silent-no-op). |
| Evidence | v4.7.16.3 commit msg: "un-silence the feature (was returning None on every tick since v4.7.3 refactor)". Bug Class #49 added to `docs/QUALITY_CONTEXT.md`. |
| Status | Closed. |
| **Fence** | When refactoring a producer, add a diagnostic sensor that would go `unavailable` or emit a known sentinel if the producer stops producing. Silent None is worse than a stack trace. Verify by reading `docs/QUALITY_CONTEXT.md` Bug Class #49. |

---

## 8. Sleep→Waking deadlock (v4.7.18.1)

**Source:** commit `59d44a71`, MEMORY.md pickup memos (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | House got stuck in `sleep` state — no organic wake. |
| Root cause | The wake transition depended on a state-change edge that could be swallowed if the occupancy raw-signal dropped exactly at the transition boundary. |
| Evidence | Commit msg: "raw-signal wake timer + daytime backstop". |
| Status | Fixed via **Option D**: raw-signal wake timer + daytime backstop. Organic wake confirmed 2026-06-05. Same night validated v4.7.13 sleep-fan trust — both master bedroom fans ran 7h continuous. |
| **Fence** | Do NOT rely solely on transition edges for state-machine exits from `sleep`. Always pair with a timer + daytime backstop. HouseStateMachine still does not persist across restart — that persistence follow-up was **DECIDED-DROPPED**; do not re-scope it without operator direction. |

---

## 9. Fan-noise / mmwave-shake saga (v4.7.19 → v4.7.22)

**Source:** git log grep `v4.7.19..v4.7.22`, planning docs `PLANNING_fan_noise_*` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | Ceiling-fan vibration shook mmWave sensors → false occupancy → fans kept running → periodic mid-sleep cycling. |
| Root cause | Presence tier lumped mmWave + PIR into one boolean (historical anchor `presence.py:3281` is stale post-v4.7.19; grep `presence.py` for the `_room_provenance` split), so a mmwave false-positive couldn't be distinguished from a PIR true-positive. |
| Evidence | Layered fix over 4 releases: v4.7.19 = per-room/per-kind `_room_provenance` split; v4.7.20 = silent truth-preserving confidence discount + decay gate; v4.7.20.1 = Bug Class #34 hotfix (see §12); v4.7.22 = Mode-2 BLE-gated fan pause+recheck, sleep-gated to protect nappers. |
| Status | Shipped and live. |
| **Fence** | Do NOT collapse presence-signal provenance back into a single boolean — the split is load-bearing for at least 3 downstream features (fan-noise mitigation, substrate unification v4.7.24, occupancy diagnostics). Any new presence feature must consume the per-kind provenance, not `_room_occupied` alone. |

---

## 10. "Study B thermostat oscillation" — NOT URA (2026-06-03)

**Source:** MEMORY.md `project_studyb_better_thermostat_oscillation` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | "Office B" / Study B Carrier TRV cycled `heat_cool` ↔ `off` every ~5 minutes. Operator suspected URA. |
| Root cause | Stale single-TRV **Better Thermostat** entry ("Master Suite Zone 1") re-armed by a bad BT update; °F/°C "implausible temp" rejection drove the mode oscillation. |
| Evidence | URA zone entity was untouched during the oscillation window; disabling the BT entry stopped it. |
| Status | Closed. URA exonerated. Operator disabled the BT entry. |
| **Fence** | Before touching a line of URA HVAC code in response to a thermostat "oscillation", **check for a Better Thermostat entry on the affected climate entity first** (`ha_get_integration better_thermostat`). Do NOT hunt in `hvac.py` / `hvac_zones.py` until BT is ruled out. |

---

## 11. Parent-entry reload → watchdog restart hazard (2026-06-03)

**Source:** MEMORY.md `feedback_parent_entry_reload_watchdog_hazard` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | Reloading the URA **parent** config entry cascaded into full re-setup → event-loop stall → supervisor watchdog restarted core (~5 min outage). |
| Root cause | Parent-entry reload triggers unload+setup on every child (rooms, zones, coordinator manager); the aggregate is slow enough to hit the watchdog. |
| Status | Documented. |
| **Fence** | Do NOT reload the URA parent entry to validate unload symmetry — the unit tests already prove it. If a change requires a full URA re-init to see the effect, deploy-restart is safer. Reload a **specific stuck child** via `homeassistant.reload_config_entry` with its `entry_id` — not a blanket reload. |

---

## 12. v4.7.20.1 conditional-import UnboundLocalError (Bug Class #34)

**Source:** commit `989f1713` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | `UnboundLocalError` on `async_dispatcher_send` in `presence._run_inference`, firing ~174×/hr. |
| Root cause | Conditional function-local `from ... import async_dispatcher_send` shadowed the module-level name; when the conditional branch didn't run, the name was unbound. Bug Class #34 recurrence. |
| Evidence | Commit msg. `docs/QUALITY_CONTEXT.md` Bug Class #34. |
| Status | Fixed. ~14 latent Bug Class #34 sites deferred (noted at time of fix). |
| **Fence** | Never write conditional function-local imports for names that could also be referenced outside the conditional. Import at module top or unconditionally at function top. When touching any file with prior Bug Class #34 history, `grep -n "from homeassistant" <file>` for local imports. |

---

## 13. Cold-boot away-actuation storm — v4.7.21 settle gates

**Source:** MEMORY.md `project_v4_7_21_boot_storm_live` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | On cold boot, slow cloud devices saturate the event loop → `house_state` aggregate freezes ~15 min while per-room sensors update fine → URA sees "away" everywhere → mass `turn_off` storm. |
| Root cause | Boot ordering: presence + house-state initialize before cloud-integration entities have restored real state. |
| Evidence | Two settle gates shipped in v4.7.21: presence released via Predicate A `real_input` (0 suppressed); HVAC Gate 2 held 2 cycles. Live-validated across 2 boots. |
| Status | Closed and validated. |
| **Fence** | Do NOT add a new boot-time actuation feature (any feature that emits a service call within the first ~2 min of setup) without gating it behind an equivalent settle predicate. The pattern is: (1) confirm `real_input` count > 0; (2) hold N cycles after first-real-input; (3) then actuate. See v4.7.21 for the reference implementation. |

---

## 14. Load Shedding pulled from queue (2026-06-08 → 2026-06-12)

**Source:** MEMORY.md `project_load_shedding_ip_capability_hold` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | Load-shedding audit surfaced 1 CRIT (EV tier shares `_paused_by_us` with EVSE TOU control — dead + unsafe to test) + 2 HIGH (orphan restore, manual-off clobber). |
| Root cause / decision | Operator 2026-06-12: "not a normal cycle." Load shedding is IP-grade capability that requires vision/architecture doc + pool sub-tier design before any build. |
| Status | **PULLED from cycle queue.** Foundations first: (a) fix EV tier `_paused_by_us` sharing (v5.4.1 landed the correctness fix — commit `32f1a72d`), then (b) pool sub-tiers + forecast-coupled shed. |
| **Fence** | Do NOT plan load shedding as a normal Tier-2 or Tier-2-DB cycle. It requires an architecture doc first. The safe-test path is obs-mode + low threshold + a single plug — **not** the EV tier. If you catch a plan proposing "add load-shed to X", stop and read the memo. |

---

## 15. Optimizer write-flood → same-day ROLLBACK (v5.0.0–v5.2.1, 2026-06-09)

**Source:** MEMORY.md `project_optimizer_db_write_flood_incident_2026_06_09`, commits `5823658e`, `216f1a1b`, `104e08d2`, `2362c937` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | v5.0.0–v5.2.1 deployed then **rolled back the same day**. Watchdog restart cycle from DB write-queue saturation. |
| Root cause | Optimizer persisted findings **one-by-one per cycle** (historical anchor `optimization.py:691` is stale post-fix; current batched path uses `log_findings_batch` / `_cap_findings` / `_dispatch_findings_updated_signal` — grep for those). Sensor-Health also fired per boot-unavailable room. The two channels saturated the single-writer queue → core writes starved → watchdog restart. Second write-flood channel (`ura_activity_log`) found in review after the first fix. |
| Evidence | v5.2.1 = LLM structured-output schema hotfix (Anthropic `additionalProperties`) — that fix was correct and kept. Rollback tag: HACS pinned to v4.7.33. Fix-forward landed as v5.2.2 (commit `104e08d2`): batch writes + suppress boot-transient findings + drop per-cycle sentinel + throttle per-room sensors + write-volume test. |
| Status | Rolled back same day; fixed-forward v5.2.2; Optimization Coordinator now runs L1 Shadow. |
| **Fence** | Do NOT design a feature that persists one-row-per-item in a periodic loop. Batch. Do NOT emit per-boot-transient sensor writes without a settle gate (see §13). Do NOT ship a DB-write-heavy feature without a write-volume test that asserts a bound on writes/hour. **Elevate any coordinator persistence work to Tier-3 review** — three framing-disjoint reviews would have converged on missing this; the 4th adversarial-completeness framing (§20) is what catches "we forgot channel N". |

---

## 16. Envoy boot incident — v5.3.7 fix (2026-06-12)

**Source:** MEMORY.md `project_envoy_boot_incident_2026_06_12`, commits `28afb796`, `517eb242`, `9512b965`, `607e69d9`, `9c3f7ed7` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | v5.3.6 booted with Envoy Enphase integration slow/unavailable → cascading URA failures. |
| Root cause | Three interacting defects: (1) `after_dependencies` stranding — URA loaded before Envoy but didn't defensively re-check; (2) one-shot Energy Coordinator validation race — validation ran once during Envoy unavailability and never retried; (3) RestoreEntity `unavailable → OFF` poisoning — restored state got interpreted as an explicit OFF. |
| Status | Fixed in v5.3.7 (three-way validation, always-register EC, deferred revalidation, manifest decouple, restore-poisoning guard, degraded observability). Exercised in anger on first boot post-fix. |
| **Fence** | Do NOT trust `after_dependencies` as a completeness guarantee — HA loads the dep, doesn't guarantee its entities are `available`. Any coordinator that reads an external integration must have a **deferred revalidation** loop, not a one-shot validate. Do NOT interpret a RestoreEntity restored value of `unavailable` as OFF — treat `unavailable`/`unknown` as "no state, wait" and gate actuation on real state. Read the v5.3.7 fix as the reference implementation. |

---

## 17. Storm Guard → inclement fusion (v5.5.0, 2026-06-15)

**Source:** `docs/planning/PLANNING_inclement_weather_reserve.md` (verified 2026-07-02), commit `77649e02`.

| Field | |
|---|---|
| Symptom | Enphase Storm Guard is cloud-only, NWS-driven, no local veto, multi-day stale locks, blunt 100% grid pre-charge. Storm reactions overshot into overnight outages, undershot on morning warnings with sunny recovery. |
| Root cause / decision | Replaced Storm Guard reliance with a local **alert + condition fusion**: `InclementFusion.decide() → InclementDecision`. Graduated hold-depth parameterized by (a) confidence tier, (b) current TOU period, (c) solar recovery horizon. The old `has_storm_forecast()` at `energy_battery.py:648-659` was **superseded** (not deleted — see the planning doc for the mechanism reuse). Enphase Storm Guard is **CONFIRMED ABSENT** as a read source in URA (planning doc says: URA never read Storm Guard directly). |
| Status | Shipped v5.5.0. Sensor `sensor.ura_inclement_state` exposes the decision. `SIGNAL_INCLEMENT_STATE_CHANGED` is the new coupling point. Open at time of memo: NWS-entity wiring UNCONFIRMED; headline gate live-unexercised. |
| **Fence** | Do NOT resurrect direct Enphase Storm Guard reads. Do NOT propose a "simpler binary storm sensor" — the graduated hold-depth is load-bearing (see arbitrage-WAIT floor gap follow-up and §20 Tier-3 D-HIGH-1). New consumers of storm/inclement state MUST subscribe to `SIGNAL_INCLEMENT_STATE_CHANGED` — do not read `has_storm_forecast()`. |

---

## 18. Battery SOC = Envoy, NOT SPAN (2026-06-16)

**Source:** MEMORY.md `project_battery_soc_envoy_not_span` (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | SPAN reported `battery_level = 97.6%` while Envoy fleet reported 71%. |
| Root cause | SPAN `battery_level` is miscalibrated in this installation. |
| Status | Operator directive: URA correctly reads `sensor.envoy_482543015950_battery`. |
| **Fence** | Do NOT propose switching battery SOC source to SPAN, or averaging the two, or "cross-validating" them. The Envoy reading is authoritative for this house. If you see divergence in a diagnostic, log it, do not swap the source. Separate open item: Enpower reserve reporting divergence (number=80 vs Envoy-reported=20) — Enphase-side, unverified, do not touch from URA. |

---

## 19. Comfort coordinator KILLED (2026-06-07)

**Source:** MEMORY.md `project_ev_offpeak_cycle_pickup` (comfort-sliders section), `PLANNING_OPTIMIZATION_COORDINATOR.md` Appendix A (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | Per-room `ComfortTempMin`/`Max`/`HumidityMax` Number entities were vestigial — RAM-only, nothing read the slider value. |
| Root cause / decision | Original intent was per-room comfort **evaluation** input for the Optimization Coordinator, not HVAC actuation. A standalone comfort coordinator was killed because fans were its only real lever, and HVAC already subsumed fans. |
| Status | Sliders **kept, not deleted**. Folded into `PLANNING_OPTIMIZATION_COORDINATOR.md` Appendix A. Persistence will be added when Optimization Phase 1 wires them. |
| **Fence** | Do NOT delete the ComfortTemp/Humidity Number entities as "dead code" — they are load-bearing for the future OC evaluation input. Do NOT propose a new standalone comfort coordinator — the only lever was fans, and HVAC owns fans. Comfort as an evaluation dimension lives inside the Optimization Coordinator. |

---

## 20. v5.5.3 Tier-3 D-HIGH-1 latent leak (2026-06-16)

**Source:** CLAUDE.md Tier-3 section, MEMORY.md `project_inclement_arbitrage_wait_floor_gap` + successor (verified 2026-07-02).

| Field | |
|---|---|
| Symptom | v5.5.3 arbitrage/attain floor fix: 3 framing-disjoint reviewers (A local, B integration, C test-authority) all returned SHIP. A dedicated 4th reviewer (D adversarial-completeness) found a real HIGH — a 7th unclamped reserve-emission site that was a latent v5.5.0 gap. |
| Root cause | Bug Class #53 (computed-but-not-consumed). The value threaded through a state machine consumed by many emission/decision sites; one missed site = silent money loss. Three converging framings did not enumerate the FULL invariant surface including pre-existing code. |
| Evidence | Commit `df57ab1e` "fix(battery): enforce inclement partial_hold floor in arbitrage + attain paths". |
| Status | Fixed. Produced the **Tier 3** review protocol (four reviews including D = adversarial-completeness with real per-site source mutation). See CLAUDE.md Tier 3. |
| **Fence** | Do NOT trust "3 reviews returned SHIP" for changes that thread a value through a state machine or shared primitive. Elevate to Tier 3 whenever ONE missed site = silent financial or safety loss. D-framing must (a) state the invariant as falsifiable, (b) enumerate the FULL surface including pre-existing code, (c) require concrete legal-config reachable repros for every flagged leak. Do NOT rely on aggregate monkeypatch tests to prove per-site coverage — use real source mutation per site. |

---

## Cross-cutting fences (single home for cross-incident rules)

These are aggregated so you do not have to read all 20 entries to find them.

| Rule | Comes from | Do NOT |
|---|---|---|
| Single-writer DB queue is invariant | §3 + §15 | Add a second DB writer path. |
| Pre-deploy zero-bugs gate is mandatory | §5 | Skip conflict-marker grep, py_compile, cycle tests, baseline diff. |
| Update listener always reloads | §4 | Add conditional reload logic. |
| Reload children, never the parent entry | §11 | Reload the parent URA entry to validate anything. |
| Boot-time actuation needs a settle gate | §13 + §15 + §16 | Actuate in the first ~2 min without a `real_input`-count + N-cycle hold. |
| RestoreEntity `unavailable/unknown` != OFF | §16 | Interpret a restored `unavailable` as an explicit OFF. |
| Provenance-split presence (per-kind) is load-bearing | §9 | Collapse per-kind provenance back into a single occupancy bool. |
| Envoy is battery SOC authority | §18 | Switch to SPAN battery_level or average the two. |
| Comfort is an evaluation dimension of OC | §19 | Delete ComfortTemp Numbers, propose a standalone comfort coord. |
| Storm/inclement consumers subscribe to signal | §17 | Add new callers of `has_storm_forecast()`. |
| Load shedding needs architecture, not a cycle | §14 | Plan load shedding as a normal Tier-2 cycle. |
| Bulk regex edits require per-file syntax gate | §1 | Ship a repo-wide regex "fix" without running py_compile per file. |
| Check Better Thermostat before URA HVAC code | §10 | Grep `hvac.py` first when a thermostat oscillates. |
| Tier 3 (4 reviews incl. D-adversarial-completeness) for state-machine-threaded values | §20 + §15 | Trust "3 reviews SHIP" on a change that could leak through one missed site. |

---

## Provenance and maintenance

Re-verify anything on this list if it might be load-bearing for a decision. One-line commands (as of 2026-07-02):

```bash
# Post-mortem files
ls -la quality/POST_MORTEM_*.md

# Incident-flavored commits (rolling)
git log --oneline | grep -iE "revert|rollback|incident|hotfix|broken|crisis"

# Bug class ledger
grep -nE "^## Bug Class #(34|46|48|49|50|51|53)" docs/QUALITY_CONTEXT.md

# Single-writer DB queue invariant
grep -nE "asyncio\.Lock|write.*queue|_write_queue" custom_components/universal_room_automation/database.py | head -20

# Storm/inclement replacement anchor
grep -n "has_storm_forecast\|InclementFusion" custom_components/universal_room_automation/domain_coordinators/energy_battery.py \
    custom_components/universal_room_automation/domain_coordinators/inclement.py | head -20

# Presence per-kind provenance anchor
grep -n "_room_provenance\|substrate_kinds" custom_components/universal_room_automation/domain_coordinators/presence.py | head -20

# Optimizer batched-persist fix
git log --oneline --all -- custom_components/universal_room_automation/domain_coordinators/optimization.py | head -10

# Envoy boot-decoupling anchors
git log --oneline | grep -E "v5\.3\.7|ec_envoy_boot"
```

**Ledger hygiene:** when a new incident closes, add one row to the index, one detail section, and — if the fix invalidates a fence in the cross-cutting table — update that table. One home per fact. If an entry becomes obsolete (e.g. the fenced path becomes safe again), do NOT delete it; mark **Status: superseded** and cite the successor.
