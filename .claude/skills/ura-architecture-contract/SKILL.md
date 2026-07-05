---
name: ura-architecture-contract
description: Load-bearing URA design decisions, invariants that must hold, and known-weak points. Load this BEFORE proposing changes that touch the DB write path, dispatcher signals, config-entry lifecycle (ROOM / ZONE_MANAGER / COORDINATOR_MANAGER), occupancy layering (substrate → room → zone → house), options-flow persistence, house-state transitions, trust hierarchies (energy sources, presence person-trust vetoes), or the reload-suppression allowlist. Also load when a reviewer or planner asks "why is it built this way", when triaging a boot storm / write-flood / stuck-state, or when the operator says "we have X" for any of these primitives. Do NOT load for pure sensor-attribute tweaks, README write-back, or one-line hotfixes that don't cross a coordinator boundary.
---

# URA Architecture Contract

Verified against repo state 2026-07-02 at v5.7.2. Every file:line was grep-read this session. Re-verify with the commands in "Provenance and maintenance" before citing in a new cycle.

This skill is the **contract**: the load-bearing decisions, the invariants you may not silently break, and the known-weak points you must plan around. It does NOT teach you HOW to build (see `homeassistant_coding`), NOR how to review (see `.claude/agents/ura-reviewer.md` / CLAUDE.md tier protocol), NOR how to deploy (see `deploy` skill). It tells you WHAT MUST REMAIN TRUE.

CLAUDE.md is authoritative. If this skill and CLAUDE.md disagree, CLAUDE.md wins — file an issue and update this skill.

---

## 0. When NOT to use this skill

| Situation | Use instead |
|---|---|
| Writing / editing an HA automation, dashboard card, helper | `homeassistant_coding` or `ha-dashboard` |
| Actually deploying a version | `deploy` |
| Writing / updating architecture prose docs | `documenter` |
| One-line sensor attribute add, README write-back, cosmetic hotfix that doesn't cross a coordinator | none — go direct |
| Capturing a fresh load-bearing decision made in this conversation | `vibememo` |
| Running the tiered review | CLAUDE.md "Review Protocol — TIERED BY SCOPE" + `.claude/agents/ura-reviewer.md` |

---

## 1. Invariants (falsifiable form)

Each invariant is stated so you can **break it in a mutation test** — flip the described condition in production source, run the suite, and confirm a specific test fails. If none fails, the invariant is untested and shipping is unsafe.

| # | Invariant | Where it lives | How to falsify (mutation) |
|---|---|---|---|
| I1 | All DB writes go through the single-writer asyncio queue. There is one `_write_task` per `UniversalRoomDatabase`; multiple `start_write_worker()` calls do NOT spawn additional workers. | `database.py:45-51` (queue init), `:56-72` (idempotent worker start) | Comment out the `if self._write_task is not None and not self._write_task.done(): return` guard; expect a test asserting single-worker idempotence to fail. |
| I2 | Read paths use independent transient `aiosqlite.connect(...)` connections (WAL allows concurrent reads); reads never share the write worker's persistent connection. | `database.py:44-48` comment; write worker persistent-connection contract at `database.py:71-80` | Route a read through the write queue; expect the write-queue-saturation regression test (post-v5.0.0 rollback) to fail. |
| I3 | `entry.options` is the **sole** source of truth for the 14 factory HVAC tunable CONFs and for CM-owned Numbers post-v4.7.26. `RestoreEntity.async_get_last_state()` is retired on those Numbers. | `number.py:716`, `:1786` ("Part 2 (post-v4.7.26): entry.options is the SOLE source of truth"), `__init__.py:4218-4243` (`_HVAC_TUNABLE_DISPATCH` — single source of truth for allowlist + dispatch) | Add a `RestoreEntity` fallback on any of the 14 keys; expect a Part-2 restore-source test to fail. |
| I4 | An options-write whose changed keys are a subset of `OPTIONS_RELOAD_SUPPRESS_KEYS` MUST be applied in place, NOT trigger a config-entry reload. Any change touching keys OUTSIDE the allowlist falls through to a full reload. | `__init__.py:4314` (frozenset), `:4757` (`if changed_keys.issubset(...)`), `:4689-4790` (`_async_update_listener`) | Add a non-allowlisted key to the frozenset; expect the reload-suppression subset test to fail. |
| I5 | HVAC tunable dispatch table (`_HVAC_TUNABLE_DISPATCH`) is the single source of truth for both allowlist membership AND runtime dispatch — the two cannot drift. | `__init__.py:4218-4243` | Add an entry to the frozenset without a dispatch row (or vice versa); expect a lockstep test to fail. |
| I6 | House-state transitions are gated by `VALID_TRANSITIONS`. No coordinator may mutate `HouseState` outside the machine. | `domain_coordinators/house_state.py:22-33` (states), `:37+` (`VALID_TRANSITIONS`) | Force an illegal transition (e.g. `AWAY → SLEEP` direct); expect the transitions test to fail. |
| I7 | `HouseStateMachine` does **NOT** persist across restart — booting always starts from AWAY and re-derives (decided-dropped per MEMORY.md 2026-06-03; see §6). | `domain_coordinators/house_state.py:100` (class), no `RestoreEntity` usage in file (verified) | Add persistence; the intentional-non-persistence behavior is unwritten policy — flag it to the operator, don't ship without checkpoint. |
| I8 | Occupancy layering is a **lattice**, not a stack: substrate is a raw-signal input consumed by BOTH room and zone tiers. It is NOT a tier. | `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` ADDENDUM; `occupancy_substrate.py:85` `OccupancySubstrate`; `presence.py:441` `ZonePresenceTracker`; `presence.py:875` `StateInferenceEngine` | Route the zone tier to bypass substrate and re-derive from raw entities; expect the v4.7.24 substrate-authority test to fail (Bug Class #50). |
| I9 | Presence signals carry provenance per-room per-kind (motion / mmwave / occupancy). Aggregate `_room_occupied` is an **OR-derived property** over `_room_provenance`, not an independently-mutable flag. | `presence.py:441+` (`ZonePresenceTracker`), v4.7.19 provenance-split | Set `_room_occupied` directly (bypassing provenance); expect the v4.7.19 provenance test to fail. |
| I10 | Night-trust hierarchy: when `house_state` is in `FAN_TRUST_STATES` (currently home_night / sleep / waking — grep `hvac.py` for `FAN_TRUST_STATES`), zone-person trust suppresses an `away` preset flip even if room sensors degenerate. Anchor via log message `"HVAC: night-trust person check errored for zone %s: %s"` (block ~`hvac.py:1245-1290`). **The 2026-06-05 "home_night not covered" gap appears CLOSED — re-verify via `grep -n 'FAN_TRUST_STATES' custom_components/universal_room_automation/domain_coordinators/hvac.py` before quoting.** | Re-grep `hvac.py` (do not cite `hvac.py:1151`; drifted). `presence.py` person-trust veto: `grep -n 'all_tracked_persons_away' custom_components/universal_room_automation/domain_coordinators/presence.py`. | Remove the FAN_TRUST_STATES gate; expect the v4.7.13/night-trust test to fail. |
| I11 | Away-state person-tracker veto fires **only when** `all_tracked_persons_away AND unidentified_count == 0`. The `unidentified_count` half preserves guest detection. | v4.7.14 emit path, `presence.py:4213` computation, `:4908` log | Drop the `unidentified_count == 0` half; expect the v4.7.14 guest-preservation test to fail. |
| I12 | Battery SOC source is Envoy, NOT SPAN (operator directive 2026-06-16, SPAN miscalibrated). | Referenced sensor `sensor.envoy_482543015950_battery` per MEMORY.md `project_battery_soc_envoy_not_span`; wired into `energy_battery.py` | Point SOC read at SPAN; expect the operator directive and battery-reserve floor tests to fail. |
| I13 | Energy strategy attain/reserve floor is threaded through the state machine — every reserve-emission site must clamp. **Bug Class #53 (computed-but-not-consumed)** — a single unclamped site is a silent-money leak. | v5.5.3 fix set (MEMORY.md), Tier-3 protocol in CLAUDE.md | Comment out one clamp site; expect the v5.5.3 reviewer-D mutation test to fail on that site (see CLAUDE.md Tier 3 framing C). |

**Any change that plausibly breaks I1, I4, I8, I10, or I13 auto-elevates to Tier 2-DB or Tier 3 review per CLAUDE.md.** When in doubt, elevate.

---

## 2. Single-writer DB queue — why, and the incident that proved it

**Design (`database.py:45-51`, verified):**

```
_write_queue: asyncio.Queue     # writes queued as coroutines
_write_task: asyncio.Task       # ONE background worker executes them serially
_db_stats: writes / reads / queue_peak
```

Writer worker started via `hass.async_create_background_task(...)` (`database.py:69-72`) so it does not block HA startup completion. `start_write_worker()` is **idempotent** (`:60-63`): multiple config entries may call it during setup; only one worker ever runs. `stop_write_worker()` cancels the task, which flushes and exits the `async with aiosqlite.connect(...)` block, closing the persistent connection (needed so exclusive `VACUUM` doesn't collide with a WAL lock — `:73-80`).

**Why not concurrent writers:** SQLite in WAL mode allows concurrent reads, but concurrent writes contend on the single writer lock. Multiple write paths caused "database is locked" incidents historically (v3.3.1.2 fix added WAL + `busy_timeout`; v3.3.1 file header; v3.22.8 introduced the queue).

**The write-flood incident (MEMORY.md `project_optimizer_db_write_flood_incident_2026_06_09`):** v5.0.0–v5.2.1 optimizer persisted findings one-by-one every cycle (historical anchor `optimization.py:691` is stale post-fix — current write path routes through `_dispatch_findings_updated_signal` / batched `log_findings_batch` DAO; grep `optimization.py` for `log_findings_batch` and `_cap_findings` for current sites); combined with Sensor-Health firing per boot-unavailable room, the queue saturated → core writes starved → supervisor watchdog restarted core. **Same-day rollback to v4.7.33.** Fix-forward requirements before re-deploy:
- batch writes (multiple rows per queued coroutine)
- suppress boot-transient findings (do not enqueue during the settle window)
- drop per-cycle sentinel writes
- throttle per-room sensor writes
- add a write-volume regression test

**Runbook implications for you:**

| Symptom | First check | Do NOT |
|---|---|---|
| "Coordinator writes stopped after boot" | Queue depth (`_db_stats["queue_peak"]`), boot-storm sensor floods | Don't spawn a parallel writer to "route around" |
| "database is locked" recurrence | WAL mode + busy_timeout still in place; long-running read holding a lock | Don't bypass the queue |
| Any new persister you write | Batch by default; expose a write-count telemetry so ±25% pre/post-deploy comparison is possible | Don't write per-tick in a hot loop |

**Live check the queue is alive:**

```bash
# via MCP ha_get_logs — look for the startup line
# "DB write worker started" (database.py:66)
# and absence of "queue_peak" spikes over sustained periods.
```

---

## 3. Config-entry types and lifecycle

Verified constants (`const.py:50-54`):

```
ENTRY_TYPE_INTEGRATION = "integration"
ENTRY_TYPE_ROOM = "room"
ENTRY_TYPE_ZONE = "zone"
ENTRY_TYPE_ZONE_MANAGER = "zone_manager"
ENTRY_TYPE_COORDINATOR_MANAGER = "coordinator_manager"
```

Dispatch in `async_setup_entry` (`__init__.py:1010`+): reads `entry.data[CONF_ENTRY_TYPE]` and routes:

| Entry type | Purpose | Setup site | Lifecycle notes |
|---|---|---|---|
| INTEGRATION | Bootstrap/parent | `__init__.py:1032`+ | Reloading the parent cascades into full re-setup → event-loop stall → **watchdog restart hazard**. Do NOT reload the parent to "validate unload symmetry" — unit tests already prove it (MEMORY.md `feedback_parent_entry_reload_watchdog_hazard`, 2026-06-03). |
| ROOM | One per physical room | Room platform fan-out | Consumes CONF sensor lists as the discovery + kind-classification source (post-v4.7.24 substrate). |
| ZONE | Individual zone | `__init__.py:126, 142, 486` | Legacy per-zone entry. |
| ZONE_MANAGER | Zone-level coordination (§v3.6.0) | `__init__.py:3051` | Manager pattern; children discovered from registered zone entries. |
| COORDINATOR_MANAGER (CM) | House-level coordinators + tuning knobs | `__init__.py:3115` | Owns the reload-suppression allowlist (§7). Options here are the sole source of truth for the 14 factory HVAC tunables (I3). |

**Options-update path (all entry types):** `entry.async_on_unload(entry.add_update_listener(_async_update_listener))` — sites at `__init__.py:2958, 3108, 3344, 3452`. The listener (`_async_update_listener`, `:4688`+) decides apply-in-place vs reload based on `OPTIONS_RELOAD_SUPPRESS_KEYS` (§7).

**Restart resilience contract:** each entry type must be safe to reload individually. Boot ordering across entries has burned URA multiple times (v4.7.21 settle gates, Envoy boot incident 2026-06-12 — MEMORY.md). Never assume a sibling entry is fully loaded when yours sets up.

---

## 4. Dispatcher signal bus

Location: `domain_coordinators/signals.py` (221 lines, verified). Contains **37+ `SIGNAL_*` constants** (grep `^SIGNAL_ ` counted 37 top-level; other assignments span ~54 references). Each is an HA-dispatcher string; naming convention `ura_<subject>_<event>`.

Key signals (each verified at the cited line):

| Signal | File:line | Emitter (typical) | Consumers to check when changing payload |
|---|---|---|---|
| `SIGNAL_HOUSE_STATE_CHANGED` | signals.py:12 | `house_state.py` | HVAC (presets), presence, energy, safety, notification_manager |
| `SIGNAL_ENERGY_CONSTRAINT` | signals.py:13 | energy family | HVAC, EVSE, load-shed candidates |
| `SIGNAL_CENSUS_UPDATED` | signals.py:14 | presence | HVAC, house_state, safety |
| `SIGNAL_SAFETY_HAZARD` | signals.py:15 | safety | notification_manager, HVAC, security |
| `SIGNAL_SECURITY_EVENT` | signals.py:17 | security | notification_manager, house_state |
| `SIGNAL_PERSON_ARRIVING` | signals.py:21 | person_coordinator / presence | house_state (`ARRIVING` transition), HVAC pre-cool |
| `SIGNAL_DATABASE_READY` | signals.py:28 | `database.py` post-init | any coordinator with `after_dependencies` on DB |
| `SIGNAL_BAYESIAN_UPDATED` | signals.py:29 | bayesian_predictor | HVAC predict, DPM |
| `SIGNAL_OCCUPANCY_ANOMALY` | signals.py:30 | presence | notification_manager, DB anomaly writer |
| `SIGNAL_NM_READY` / `_BAYESIAN_READY` / `_ENERGY_COORDINATOR_READY` / `_HVAC_COORDINATOR_READY` | signals.py:63, 64, 72, 80 | each coordinator on startup | wiring gates for late subscribers |
| `SIGNAL_INCLEMENT_STATE_CHANGED` | signals.py:95 | inclement.py | energy strategy (v5.5.0 hold), HVAC |
| `SIGNAL_DYNAMIC_PRESET_TRANSITIONED` | signals.py:100 | dynamic_preset.py | HVAC apply, telemetry |
| `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` / `_FAN_RECHECK_STARTED` / `_FINISHED` | signals.py:125, 130, 134 | presence_fan_recheck | HVAC (fan pause), presence provenance |
| `SIGNAL_SUBSTRATE_KIND_CHANGED` | signals.py:147 | occupancy_substrate | room tier, zone tier |
| `SIGNAL_OPTIMIZER_INTENT` / `_VETO` / `_FINDING_EMITTED` | signals.py:164, 165, 166 | optimization.py | safety veto, DB writer |

**Contract on adding a signal:**
1. Grep the exact new SIGNAL name across `custom_components/` and `quality/tests/` before adding — reuse if found (Institutional-Context-First rule, CLAUDE.md).
2. Add the constant to `signals.py` next to its family, not scattered.
3. If the payload shape changes, this is a **Tier 2-DB Review B trigger** — every migrated call site must produce equivalent dispatch AND no double-emit (CLAUDE.md).
4. Import from `signals.py` at module level. **Never** do a conditional function-local `async_dispatcher_send` import — that's Bug Class #34 (v4.7.20.1 hotfix, MEMORY.md).

---

## 5. Occupancy layering (the lattice)

Source of truth: `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` ADDENDUM (verified). The **substrate is NOT a tier**.

```
House tier    StateInferenceEngine.infer()        presence.py:875
  ↑ consumes composite zone signals (any_zone_occupied, any_zone_raw_occupied)
Zone tier     ZonePresenceTracker                 presence.py:441
  ↑ derived OR over _room_provenance; raw_occupied for v4.7.18.1 wake timer;
    fan-interference hold extension; camera timeout; BLE precedence
Room tier     RoomCoordinator (coordinator.py)
  ↑ 900s timeout decay, failsafe force-vacant, camera+BLE override,
    2s rate-limited Tier-1 refresh with trailing-edge async_refresh()
Occupancy substrate    OccupancySubstrate         occupancy_substrate.py:85
  ← driven exclusively by CONF_MOTION_SENSORS / CONF_MMWAVE_SENSORS /
    CONF_OCCUPANCY_SENSORS per room. Shared raw input for room AND zone tiers.
```

**Per-tier ownership (do NOT relocate between tiers):**

| Tier | Owns |
|---|---|
| Room | Decay timeouts, failsafe force-vacant, camera + BLE overrides, rate-limited refresh |
| Zone | Composition policy (`_room_occupied` OR over provenance), `raw_occupied` semantics, fan-interference hold extension, camera timeout, BLE precedence in `_derived_mode` |
| House | `StateInferenceEngine.infer()` over zone composites |
| Substrate | Discovery + kind-classification from CONF lists — **and nothing else** |

**Bug Class #50 (Substrate subscription clobbered):** the substrate subscription set is periodically rebuilt by `_update_signal_subscriptions`; if you add a subscriber, register it on every rebuild, not once at setup. See MEMORY.md v4.7.24 entry + CRITICAL B-C1.

**Provenance rule (v4.7.19):** `_room_occupied` is a derived OR property over per-kind `_room_provenance` (motion / mmwave / occupancy). Never set `_room_occupied` directly. Splitting provenance was a **prerequisite** to the fan-noise mmwave mitigation family (backlog).

---

## 6. `HouseStateMachine` — the "does not persist" decision

Source: `domain_coordinators/house_state.py:22-33` (states), `:37+` (transitions), `:100` (class). Verified there is NO `RestoreEntity` usage in `house_state.py`.

**States:** `AWAY | ARRIVING | HOME_DAY | HOME_EVENING | HOME_NIGHT | SLEEP | WAKING | GUEST | VACATION` (StrEnum).

**Decision (MEMORY.md v4.7.18.1 entry, 2026-06-05):** the machine boots AWAY and re-derives. Persistence follow-up **DECIDED-DROPPED**. The invariant is unwritten policy — do not add `RestoreEntity` restore without an operator checkpoint.

**Why non-persistence is deliberate:** at boot, sensor state is uncertain (BLE not corroborated, cameras warming, mmWave settling). Trusting a stored state can trap the house — see the v4.7.18.1 sleep→waking deadlock. Fresh derivation with settle gates (v4.7.21) is the durable pattern.

---

## 7. Options-flow as sole source of truth + reload-suppression allowlist

**Contract (I3, I4):** for the CM-owned tunable set, `entry.options` is authoritative; RestoreEntity is retired. An options change writes `entry.options`, then `_async_update_listener` chooses:

- **Apply in place** if `changed_keys ⊆ OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:4757`) — push new values to live coordinator attrs via `_apply_in_place` (`__init__.py:4391+`), advance the snapshot, no reload.
- **Reload** otherwise (`__init__.py:4779, 4785`).

The allowlist frozenset: `OPTIONS_RELOAD_SUPPRESS_KEYS` at `__init__.py:4314` (verified). Grew across v4.7.26 → v4.7.27 (Cycle 1 HVAC presence timers + DPM dwell; Cycle 2 broader keys). MEMORY-recorded growth "5 → 37" is **unverified** in this fix pass — re-verify with `grep -c '"' <(sed -n '/OPTIONS_RELOAD_SUPPRESS_KEYS = frozenset/,/})/p' custom_components/universal_room_automation/__init__.py)` before quoting a specific number.

**Dispatch tables (single source of truth, do NOT drift):**

| Table | File:line | What it holds |
|---|---|---|
| `_HVAC_TUNABLE_DISPATCH` | `__init__.py:4228-4243` | 14 HVAC factory CONFs → `(sub_controller_attr, runtime_field, cast_type)`. Membership == allowlist membership. |
| `_EC_SETTER_DISPATCH` | `__init__.py:4248-4254` | Energy Coordinator setter-based dispatch (calls a coordinator setter, NOT `setattr`, because the setter runs side-effects like `_check_threshold_ladder`). |
| `_OFFPEAK_DRAIN_QUALITY` | `__init__.py:4257-4262` | Off-peak drain quality → key. |
| `_NO_LIVE_ATTR_KEYS` | `__init__.py:4280-4312` | Keys where the listener only advances the snapshot; consumer re-reads `entry.options` on next tick. |

**Contract on adding a CM tunable:**

1. Decide dispatch style: direct `setattr` (add to `_HVAC_TUNABLE_DISPATCH`) OR setter (add to `_EC_SETTER_DISPATCH`) OR read-fresh-per-cycle (add to `_NO_LIVE_ATTR_KEYS`).
2. Add the CONF to `OPTIONS_RELOAD_SUPPRESS_KEYS` if and only if you can apply it in place safely.
3. Verify the runtime field is consumed **inline at the call site**, not stashed in a cache (`__init__.py:4223-4227` comment lists the 5 watch-list keys already verified — replicate that grep for any new watch-list candidate).
4. Retire any `RestoreEntity` fallback on the associated Number (I3).

**Post-restart behavior:** entries re-seed values from `entry.options` at setup — no restore-from-last-state on the tunable set. The v4.7.27 Review-D live validation confirmed this (MEMORY.md).

---

## 8. Trust hierarchies

### 8a. Energy source trust

Operator directive 2026-06-16 (MEMORY.md): **battery SOC is read from Envoy, NOT from SPAN.** Cited entity: `sensor.envoy_482543015950_battery`. SPAN battery_level was miscalibrated (97.6% vs true 71%). If you touch battery reads, verify the Envoy path in `energy_battery.py`.

Enphase-side divergence: Enpower `number` (reserve=80) vs Envoy-reported reserve (=20) is a KNOWN, unverified upstream mismatch. Do not "fix" URA to paper over it.

### 8b. Presence person-trust vetoes

Two vetoes, DIFFERENT scopes:

| Veto | When it fires | Where | Preserves |
|---|---|---|---|
| Night-trust (v4.7.13 → widened) | `house_state` in `FAN_TRUST_STATES` — trusts `person.*=home` even if mmWave/PIR both drop | Re-grep `hvac.py` for `FAN_TRUST_STATES` (block ~L1245-1290; do not cite `:1151`). | Master bedroom fan/preset continuity through night. home_night **appears covered by FAN_TRUST_STATES** — verify with grep before quoting. |
| Away-state veto (v4.7.14) | `all_tracked_persons_away AND unidentified_count == 0` → `HouseState.AWAY` @ 0.95 confidence | `presence.py:930, 1198, 4213, 4908` (all verified) | Guest detection — dropping the `unidentified_count == 0` half breaks guests. |

**"Zone away while occupied" gap (MEMORY.md, 2026-06-05, unbuilt):** `hvac.py:1055` D1 vacancy override retreats AC when mmWave drops the still body in bed during `home_night`. Fix candidate = extend person-trust to `home_night` (Tier-1 sibling of v4.7.13). Bed sensor is an unused signal.

---

## 9. Coordinator dependency map (verify by grep before changing)

Coordinators (`domain_coordinators/` verified 2026-07-02):

```
presence / occupancy_substrate / presence_fan_recheck
energy / energy_battery / energy_pool / energy_tou /
   energy_forecast / energy_billing / energy_circuits
hvac / hvac_zones / hvac_override / hvac_predict /
   hvac_egress / hvac_fans / hvac_covers / hvac_preset /
   hvac_setpoint / dynamic_preset / preset_overrides
safety / security / house_state / notification_manager
optimization / optimization_llm
inclement / weather_manager
regime_detector / routine_forecaster / music_following
manager / signals / base
```

Cross-cutting root files: `aggregation.py`, `bayesian_predictor.py`, `transitions.py`, `person_coordinator.py`, `pattern_learning.py`.

**Rule:** before changing a signal payload or coordinator interface, run:

```bash
grep -rn "SIGNAL_<NAME>" custom_components/universal_room_automation/ quality/tests/
```

Every hit is a consumer to check. This is the concrete form of the Institutional-Context-First rule (CLAUDE.md).

---

## 10. Known-weak points (stated plainly)

| Weak point | Evidence | Mitigation posture |
|---|---|---|
| **God-file sizes** verified `wc -l` 2026-07-02: `sensor.py`=14337, `config_flow.py`=8889, `database.py`=7070, `presence.py`=6160, `energy.py`=5955 | Live grep this session | Do not add gratuitously to god files; carve new coordinators into `domain_coordinators/`. Refactor cycles need Tier 2-DB elevation. |
| **No CI** | 504 releases in 6 months, gates are process-only | `deploy` skill runs tests locally; Pre-Deploy Zero-Bugs Gate (MEMORY.md) is mandatory: grep conflict markers + `py_compile` changed files + cycle tests + suite-baseline-diff. |
| **Boot ordering** | Envoy boot incident 2026-06-12 (after_dependencies stranding); v4.7.21 settle gates; boot-storm actuation history (MEMORY.md) | Never assume sibling entry is loaded; gate on `_READY` signals (§4); add settle gates for cold-boot windows; do not enqueue transient findings during settle. |
| **`HouseStateMachine` non-persistence** (I7) | `house_state.py:100` class, no RestoreEntity | Deliberate. Do NOT add persistence without operator checkpoint. |
| **`_room_provenance` subscription-rebuild clobber** (Bug Class #50) | v4.7.24 B-C1 CRITICAL (MEMORY.md) | Re-subscribe on every rebuild, not once at setup. |
| **Bug Class #53 — computed-but-not-consumed** | v5.5.3 D-HIGH-1 (leak at one un-clamped reserve site) | Tier 3 review protocol; reviewer D re-enumerates the full invariant surface (pre-existing code included). |
| **Bug Class #34 — conditional function-local dispatcher import** | v4.7.20.1 hotfix | Always import `async_dispatcher_send` at module level. |
| **Silent-actuator failure** (2026-07-01, `sensor.<room>_unavailable_entities` covers inputs but not actuators until v5.7.2) | MEMORY.md `project_session_pickup_2026_07_02` + CLAUDE.md Troubleshooting | v5.7.2 added actuator visibility; when diagnosing "automation broke", check actuator availability FIRST (CLAUDE.md runbook). |
| **Reload-suppression allowlist drift** | I5 lockstep table | Enforce dispatch-table + allowlist parity in a test; grow allowlist deliberately. |
| **god-file config_flow** | 8889 LoC | Field additions must reference existing sections; do not duplicate. |

---

## 11. Change-safety checklist (paste into your planning doc)

Before proposing any change that touches this contract, complete the checklist:

- [ ] Read CLAUDE.md sections "Subagent Usage Protocol", "Institutional Context First", "Review Protocol — TIERED BY SCOPE".
- [ ] Grepped every proposed CONF / SIGNAL / helper / constant across `const.py`, `config_flow.py`, `signals.py`, `domain_coordinators/*.py`, `sensor.py`, `binary_sensor.py`, `number.py`, `switch.py`, `select.py`, `button.py`. Cited REUSED (file:line) or NEW (why nothing found).
- [ ] Skimmed relevant `docs/planning/PLANNING_*.md` filenames; pulled bodies for anything touching the same coordinator surface.
- [ ] Pulled relevant `docs/Coordinator/<NAME>.md` design doc(s).
- [ ] Pulled memory bodies (not just index lines) for related shipped / backlog / live cycles.
- [ ] Stated the falsifiable invariant this change must preserve (§1).
- [ ] Classified tier — Tier 1 hotfix / Tier 2 feature / Tier 2-DB / Tier 3 (regression-prone default is Tier 2-DB per CLAUDE.md 2026-06-08 standing policy).
- [ ] Wrote `README_v<version>.md` in `docs/readmes/` with prospective Live Validation criteria BEFORE deploy; planned the post-restart write-back.
- [ ] Tagged pre-review baseline: `git tag pre-review-v<version> -m "Pre-review baseline"`.
- [ ] If touching DB write path: batched writes, no per-tick emitters, write-volume regression test staged.
- [ ] If touching options-flow: decided dispatch style, verified `entry.options` sole-source-of-truth pattern, no `RestoreEntity` fallback.
- [ ] If touching presence: preserved lattice (§5), preserved provenance OR-derivation, preserved person-trust vetoes.
- [ ] If touching energy strategy: enumerated every reserve-emission / clamp site; ran Tier 3 reviewer-D adversarial mutation.

---

## 12. Fallback when live tooling is down

Samba remount command + MCP tool inventory live in
`ura-diagnostics-and-tooling` § Live-access commands (fact-home). SSH
fallback into the HA host to read `.storage/core.config_entries`
directly answers "which entities does this room drive". Do NOT guess
actuator identities from friendly names (CLAUDE.md Troubleshooting —
AV Closet example).

---

## Provenance and maintenance

Every claim above was grep-read this session 2026-07-02 at v5.7.2. Re-verify with:

```bash
# Section 1 (invariants) anchors
grep -n "start_write_worker\|_write_task\|_write_queue" custom_components/universal_room_automation/database.py
grep -n "OPTIONS_RELOAD_SUPPRESS_KEYS\|_HVAC_TUNABLE_DISPATCH\|_EC_SETTER_DISPATCH\|_NO_LIVE_ATTR_KEYS" custom_components/universal_room_automation/__init__.py
grep -n "class HouseState\|VALID_TRANSITIONS\|class HouseStateMachine" custom_components/universal_room_automation/domain_coordinators/house_state.py

# Section 3 (entry types)
grep -n "^ENTRY_TYPE" custom_components/universal_room_automation/const.py
grep -n "add_update_listener\|_async_update_listener" custom_components/universal_room_automation/__init__.py

# Section 4 (signals)
grep -c "^SIGNAL_" custom_components/universal_room_automation/domain_coordinators/signals.py
wc -l custom_components/universal_room_automation/domain_coordinators/signals.py

# Section 5 (lattice)
grep -n "class OccupancySubstrate\|class ZonePresenceTracker\|class StateInferenceEngine" custom_components/universal_room_automation/domain_coordinators/*.py custom_components/universal_room_automation/*.py
sed -n '1,80p' docs/Coordinator/COORDINATOR_ARCHITECTURE.md   # ADDENDUM

# Section 8 (person trust)
grep -n "all_tracked_persons_away\|person-tracker veto" custom_components/universal_room_automation/domain_coordinators/presence.py

# Section 10 (god files)
wc -l custom_components/universal_room_automation/sensor.py custom_components/universal_room_automation/config_flow.py custom_components/universal_room_automation/database.py custom_components/universal_room_automation/domain_coordinators/presence.py custom_components/universal_room_automation/domain_coordinators/energy.py
```

If any command returns a materially different result, this skill is stale — update the affected section and date-stamp it.

Sibling skills to keep in sync when this changes: `deploy` (uses I1/I3/I4 during pre-deploy gate), `homeassistant_coding` (should reference §5 lattice + §7 options pattern), `documenter` (mirrors §9 map in prose docs).
