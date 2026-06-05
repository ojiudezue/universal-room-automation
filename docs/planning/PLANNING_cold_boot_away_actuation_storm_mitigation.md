# PLANNING — Cold-boot Away-Actuation Storm Mitigation

**Status:** Draft for review (no code written)
**Cycle type:** Behavioral hardening (boot-path)
**Versioning:** Per operator convention, version number assigned at deploy. NOT shipping this doc with a version in the filename.
**Owner:** ura-planner → ura-builder
**Related memos:** `project_v4_7_19_live` (root-cause writeup), `project_v4_7_18_1_sleep_wake_deadlock` (HouseStateMachine non-persistence — decided & dropped), `project_ec_startup_race_evidence` (sibling boot-race).

---

## 0. Problem statement (verified, recurring)

On every URA cold boot, the per-process `HouseStateMachine` initializes to `HouseState.AWAY` (`domain_coordinators/house_state.py:111`). The Presence Coordinator's first inference runs before sensors have settled (`domain_coordinators/presence.py:1807` — `await self._run_inference("startup")`). As census data and zone signals trickle in across the next 10-60s, inference flips state — typically through `AWAY → HOME_DAY` and (during noisy boot windows) back through `HOME_DAY → AWAY` — and each accepted transition dispatches `SIGNAL_HOUSE_STATE_CHANGED` (`presence.py:4457`).

Every accepted dispatch fans out to:
- All room coordinators' `_on_house_state_changed` (`coordinator.py:447`), which fire user-configured chained HA automations bound to `chain_house_state_*` triggers. The operator's `chain_house_state_away` chain calls `homeassistant.turn_off` / `light.turn_off` / `switch.turn_off` across the configured device sets for every room in scope.
- HVAC's `_handle_house_state_changed` (`domain_coordinators/hvac.py:1249`), which kicks an immediate decision cycle (preset re-application; fan re-evaluation).
- Security's auto-follow path (`domain_coordinators/security.py:663`).

Many of those service calls target slow cloud devices (meross_lan, tplink, smartthings, dreo, sonoff, mqtt) that don't ACK promptly. Even with `blocking=False`, the resulting service-call burst, dispatcher fan-out, and downstream cloud-bound writes saturate the event loop. Symptoms observed and re-observed:
- Home Assistant bootstrap logs "Setup timed out for stage 2" (within ~3-5 min of restart) and "Something is blocking start up" (~6 min).
- The presence DOMAIN coordinator's debouncer-driven refresh becomes a starved task; the aggregate sensor `sensor.ura_presence_coordinator_presence_house_state` freezes for ~15 min showing only `icon`+`friendly_name` attributes while per-room `binary_sensor.<room>_occupied` sensors update fine (their update path is a state-change listener, not the starved coordinator refresh — that asymmetry is the diagnostic tell).
- MCP API CONNECTION_TIMEOUT / HTTP 000 for several minutes during the storm.

**Reproducibility.** Recurred on the v4.7.19 boot AND the v4.7.20.1 boot (2026-06-03/04). Not a regression — long-standing boot behavior.

**Out of scope for this cycle.** EC `not_initialized` startup-race (sibling symptom, separate investigation in `project_ec_startup_race_evidence`); HouseStateMachine restart-persistence (DECIDED, DROPPED 2026-06-03 — see `docs/planning/DECISION_house_state_restart_persistence.md`).

---

## 1. Institutional context verified

Format per CLAUDE.md "Institutional Context First" protocol — every proposed addition tagged REUSED (with file:line) or NEW (with justification).

### 1.1 Greps run + REUSED/NEW for each proposed addition

| Proposed addition | Status | Notes |
|---|---|---|
| Boot-grace flag on Presence Coordinator (`self._boot_settle_done: bool`) | NEW | Grep `settle\|boot.*delay\|grace\|first_compute\|CONF_BOOT\|cold.*boot` across `custom_components/universal_room_automation/`: no existing module-level boot-settle / boot-grace state machine on any coordinator. The HVAC coordinator's `await presence._ready_event.wait()` (`hvac.py:474-476`) is a one-shot "presence has had its `async_setup` complete" gate; it is NOT "first REAL compute has happened" and does not gate house-state dispatch. We need a strictly stronger gate. |
| Suppress-while-settling guard inside `_run_inference` dispatch path (around `presence.py:4448-4466`) | REUSED (pattern) | The existing `if self.observation_mode:` branch at `presence.py:4448` already proves the same code path can suppress `SIGNAL_HOUSE_STATE_CHANGED` dispatch without disturbing state-machine logic. Same shape used at `presence.py:2998` and `:3260` for SIGNAL_CENSUS_UPDATED and SIGNAL_PERSON_ARRIVING. The new boot-suppression branch will mirror this pattern — same gate, different trigger. |
| HA-core-started wait hook (`hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, ...)`) | NEW | Grep `EVENT_HOMEASSISTANT_STARTED\|hass\.is_running\|CoreState\.running` across the integration: zero matches. URA currently has no listener that waits for HA's CoreState to reach `RUNNING`. This is a genuine gap. |
| "First REAL compute" predicate | NEW | No prior `_has_real_compute` / `_first_inference_complete` flag exists on Presence. The closest analog is `_ready_event` (set after `_run_inference("startup")` returns regardless of result). We need a stricter "inference saw non-empty inputs" predicate — see §3.D2. |
| Settle-delay timeout constant | NEW | Existing timeouts in the area: `hvac.py:476` waits 10s on Presence ready; `__init__.py:2459` references a 120s cold-boot bootstrap budget; egress force-release uses 60s (`hvac.py:593`). Default chosen: 60s ceiling — same shape as the egress force-release — see §3.D3. |
| Persisted "last known house_state" for boot seeding | REJECTED (DROPPED per memo) | The 2026-06-03 operator decision drops `HouseStateMachine` restart-persistence (`docs/planning/DECISION_house_state_restart_persistence.md`). This cycle MUST NOT re-propose it. The mitigation works WITHOUT persistence by suppressing dispatch until inference inputs are real. |
| Room coordinator `_skip_first_automation` reuse | NOTED (existing) | `coordinator.py:192,1892` already suppresses the per-ROOM first-tick entry/exit automation. This cycle is about the orthogonal HOUSE-STATE-driven dispatch storm — `_skip_first_automation` does NOT cover it. |
| CONF_* added | NONE | Plan ships ZERO new config-flow fields. Behavior is automatic and bounded (timeout + failsafe). Operator override not required for v1. If post-deploy tuning is needed, a `CONF_BOOT_SETTLE_SECONDS` Number field can be added in a follow-up cycle. |

### 1.2 Prior planning docs consulted

- `docs/planning/PLANNING_v4.7.18.1_sleep_wake_deadlock.md` — full read. Establishes that `HouseStateMachine` does NOT persist across restart and the operator-final decision to NOT add persistence. Constrains this plan to dispatch-side mitigation only.
- `docs/planning/PLANNING_v4.7.19_presence_provenance_split.md` (referenced via memo) — skimmed. Confirms `_room_occupied` is a derived `@property` over per-kind provenance dicts; nothing in that cycle gates dispatch.
- `docs/planning/PLANNING_v4.7.20_fan_noise_layer1.md` (referenced via memo) — skimmed. Layer-1 silent occupancy-hold logic is observation-only and lives in inference, not in dispatch.
- `docs/planning/PLANNING_v4.7.15_universalize_bug_class_48_veto.md` — skimmed. Same bug class as the v4.7.14 person-tracker veto: a defensive predicate in `_run_inference`. Pattern reused stylistically.
- `docs/PLANNING_v3.6.0_REVISED.md` (root vision for domain coordinators) — skimmed. Confirms Presence Coordinator owns house-level state and is the ONLY publisher of `SIGNAL_HOUSE_STATE_CHANGED`. Mitigation point of control is correctly Presence.

### 1.3 Memory bodies pulled

- `project_v4_7_19_live` — full body. Diagnostic tell (per-room sensors update, aggregate freezes) verified against this memo; mitigation rationale derived from it.
- `project_v4_7_18_1_sleep_wake_deadlock` — full body. House-state non-persistence constraint sourced here.
- `project_ec_startup_race_evidence` — full body. Marked sibling, OUT of scope. Different surface (EC switch RestoreEntity races). Listed so the builder doesn't conflate them.

### 1.4 Per-coordinator design docs read

- `docs/Coordinator/PRESENCE_COORDINATOR.md` — read §1-§4. Reaffirms "Presence Coordinator provides STATE, not ACTIONS." This plan respects that: we modify STATE-publication timing, not actions.
- `docs/Coordinator/COORDINATOR_ARCHITECTURE.md` — skimmed for signal-flow contract. Confirms `SIGNAL_HOUSE_STATE_CHANGED` is the sole inter-coordinator notification for house-state changes.

### 1.5 Code locations surveyed (read end-to-end during scoping)

- `domain_coordinators/house_state.py:1-180` — `HouseStateMachine` initial state (`AWAY` at `:111`), hysteresis table, `transition()`. **Cited.**
- `domain_coordinators/presence.py:1640-1817` — `async_setup`, census seed, `_run_inference("startup")` at `:1807`, `_ready_event.set()` at `:1811`. **Cited.**
- `domain_coordinators/presence.py:4396-4485` — dispatch site for `SIGNAL_HOUSE_STATE_CHANGED`; existing `observation_mode` gate at `:4448-4466`. **Cited.**
- `domain_coordinators/presence.py:1175-1176` — `self.observation_mode` declaration (pattern reused). **Cited.**
- `domain_coordinators/hvac.py:425-500` — house-state subscription + `_ready_event` wait. **Cited.**
- `domain_coordinators/hvac.py:1248-1276` — `_handle_house_state_changed` (immediate decision-cycle kick). **Cited.**
- `domain_coordinators/security.py:663,916-980` — auto-follow handler. **Cited.**
- `domain_coordinators/manager.py:130-280` — CM construction, `HouseStateMachine` ownership at `:143`, coordinator setup ordering at `:265`. **Cited.**
- `coordinator.py:354-498` — `_fire_chained_automations` + `_on_house_state_changed` (per-room user-chain trigger). **Cited.**
- `coordinator.py:188-200, 1885-1965` — `_skip_first_automation` declaration + first-refresh suppression for per-room entry/exit (orthogonal, but confirms the "skip first" pattern already lives in URA). **Cited.**
- `automation.py:580-870` — per-room `_handle_exit` → `_control_lights_exit` → `_control_auto_switches(False)` → `_control_manual_switches_off`. These are the per-room turn_off sites; they fire on room-occupancy exit, NOT directly on house-state. Confirmed they are NOT the primary storm source — the storm is the user's HA `chain_house_state_away` automations firing across every room coordinator simultaneously. **Cited.**
- `__init__.py:2762-2800` — existing room-state pre-restore (`_last_occupied_state` from DB) that already prevents the per-room "false entry" storm. The HOUSE-state storm is orthogonal and NOT covered by this v3.22.12 fix. **Cited.**

---

## 2. Tier classification

**Operator-elevated Tier 2.** Justified below.

This change is small in LoC (estimated ~80-130 LoC of behavioral code + ~40-60 LoC of tests), which under a naive reading would slot as Tier 1. We elevate to Tier 2 because:

1. **Trust-hierarchy ripple.** The change modifies the timing of the ONE signal (`SIGNAL_HOUSE_STATE_CHANGED`) that wires Presence to HVAC, Security, and every user-configured chained automation. A late dispatch, a dropped dispatch, or a missing failsafe-release event silently breaks three coordinators and the user's HA-side automation surface. This is exactly the "small surgical fix risks regressions across multiple coordinators (presence ↔ HVAC ↔ compliance ↔ safety)" criterion in CLAUDE.md for operator-elevated Tier 2-DB. We are NOT elevating to Tier 2-DB because there are no DB-side changes — but the cross-coordinator risk justifies two parallel reviews.
2. **No fast rollback if wrong.** A miss here ships either as a persistent "URA never reacts to house state on Monday morning" (failsafe-release bug) or as a regression of the storm itself (suppression-window too tight). Both are silent at deploy time.
3. **Async lifecycle subtlety.** The change interacts with `EVENT_HOMEASSISTANT_STARTED`, `_ready_event`, and the periodic-inference timer. Three async surfaces; framing-disjoint reviews recommended.

**Tier 2 review framings (recommended dispatch):**
- **Reviewer A — Correctness + edge cases.** Does the suppression release on every reachable path? What happens if HA never reaches RUNNING? What happens during `homeassistant.restart` (soft restart, not cold boot)? What happens if Presence's `async_setup` raises after partial init? What about a config reload mid-suppression?
- **Reviewer B — Async lifecycle + race conditions.** What if `EVENT_HOMEASSISTANT_STARTED` fires BEFORE `async_setup` registers its listener? What if the inference timer ticks while suppression is being released? Cancel/cleanup symmetry on entry unload. No untracked background tasks (Bug Class #19). Dispatcher listener leakage on reload (Bug Class #1 / #5).

If the builder's implementation drifts into NEW config-flow surfaces or anomaly-detector schema, escalate to Tier 2-DB.

---

## 3. Deliverables

### D1: Add `_boot_settle_done` gate to Presence Coordinator

**What.** Introduce a single boolean (and supporting timestamp) on `PresenceCoordinator` that starts `False` at construction and flips `True` exactly when the FIRST inference tick completes against REAL inputs (defined in D2). Until it flips, the existing `SIGNAL_HOUSE_STATE_CHANGED` dispatch site at `presence.py:4448-4466` short-circuits with an INFO log — mirroring the existing `observation_mode` branch. The HouseStateMachine `.transition()` call still happens (state machine stays correct internally); only the cross-coordinator + chained-automation FAN-OUT is held.

**Files.**
- `custom_components/universal_room_automation/domain_coordinators/presence.py` — declare `self._boot_settle_done: bool = False` + `self._boot_settle_started_utc: datetime | None = None` near `:1175`. Add suppression branch around `:4448` (parallel to the observation_mode branch). The suppression must coexist with observation_mode (BOTH gates can suppress; only one log line emitted, preference: boot-settle wins for clarity).
- `custom_components/universal_room_automation/const.py` — add `BOOT_SETTLE_TIMEOUT_SECONDS: Final = 60` and `BOOT_SETTLE_MIN_INPUTS = 1` (see D2). Module-level Final constants, NOT a `CONF_*` (no user-facing knob in v1 per §1.1).

**Bug-class guards.**
- Bug Class #1 (coordinator lifecycle): no `async_added_to_hass` mis-use; we're in domain coordinator `async_setup`.
- Bug Class #14 (config snapshot staleness): `BOOT_SETTLE_*` are module-level constants — no per-tick stale read.
- Bug Class #22 (enum value mismatch): NOT applicable (no new enum).
- Bug Class #23 (incomplete observation-mode gating): explicitly mirror the existing observation_mode site (`:4448`) and document that both gates AND together (either suppresses).

### Acceptance Criteria

- **Verify:** With `self._boot_settle_done = False`, an `async_dispatcher_send(SIGNAL_HOUSE_STATE_CHANGED)` call from `_run_inference` is NOT made; INFO log "boot-settle: suppressing SIGNAL_HOUSE_STATE_CHANGED <old> → <new>" is emitted instead. After the gate flips, the next inference tick that produces a different state DOES dispatch.
- **Test:** `test_boot_settle_suppresses_initial_dispatch` — boot fixture (fresh PresenceCoordinator, manager wired, no census seeded); call `_run_inference("startup")`; assert no dispatch received on a captured dispatcher mock. Then trigger the release path (D3); call `_run_inference("census_update")`; assert dispatch fires when state changes.
- **Test:** `test_boot_settle_does_not_block_state_machine_internally` — assert `manager.house_state_machine.state` updates even while suppressed, so the system's INTERNAL view of house state stays consistent.
- **Live:** post-deploy, journald shows at least one "boot-settle: suppressing" INFO line within the first 60s of `Setting up Presence Coordinator`, followed within ≤2 min by a normal `SIGNAL_HOUSE_STATE_CHANGED` dispatch INFO line.

---

### D2: "First REAL compute" predicate

**What.** Define WHAT counts as a real first compute so the gate flips at the right moment — not too eagerly (the bug today is dispatching on an empty initial inference) and not too late (must release before users start interacting). The predicate has TWO release paths in OR:

**Predicate A (preferred — input-driven release):** flip `_boot_settle_done = True` at the START of the FIRST `_run_inference` tick where ANY of:
1. `self._census_count > 0`, OR
2. `any_zone_occupied is True` (computed inside the inference body — already available), OR
3. The trigger of the inference call is NOT `"startup"` AND NOT `"periodic"` (i.e., the first event-driven inference: `census_update`, `occupancy_change`, `camera_detection`, `geofence_arrive`, `geofence_leave` — anything that came from a real observed change).

Rationale: each of these conditions means inference is operating on observed-world data, not the construction-time defaults. The "no longer empty" check is what `BOOT_SETTLE_MIN_INPUTS` represents.

**Predicate B (failsafe — time-driven release):** flip `_boot_settle_done = True` exactly once when `EVENT_HOMEASSISTANT_STARTED` fires, OR `BOOT_SETTLE_TIMEOUT_SECONDS` (default 60s) since `async_setup` start, WHICHEVER COMES FIRST. This guarantees the gate is bounded even if Predicate A never fires (e.g., empty house, no sensors firing).

**Important nuance.** The gate flip happens BEFORE the dispatch decision in the same `_run_inference` tick, so the first real dispatch is NOT suppressed. The order is: `if not _boot_settle_done and <Predicate A>: _boot_settle_done = True` → then the existing dispatch branch evaluates the gate as already-released.

**Files.**
- `domain_coordinators/presence.py` — add the Predicate A check near the top of `_run_inference` (after current_state read, before transition acceptance). Add the Predicate B wiring in `async_setup`: `self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._on_ha_started_release_boot_settle)` AND `async_call_later(self.hass, BOOT_SETTLE_TIMEOUT_SECONDS, self._timeout_release_boot_settle)`. Both release handlers must be idempotent (`if self._boot_settle_done: return`) and must be appended to `self._unsub_listeners` for cleanup symmetry on entry unload.

**Bug-class guards.**
- Bug Class #5 (startup races): explicitly two-of-three release paths means no single race can leave the gate stuck `False`.
- Bug Class #19 (untracked background tasks): the `async_call_later` return value MUST be stored and cancelled on unload via `_unsub_listeners`.
- Bug Class #1 / #28: `_on_ha_started_release_boot_settle` is `@callback`, not async; release is synchronous.

### Acceptance Criteria

- **Verify (input-driven release):** with census_count=1 seeded into `_run_inference("startup")`, the gate flips BEFORE the dispatch site runs, and the first AWAY→HOME_DAY transition DOES dispatch.
- **Verify (HA-started release):** with empty house, no sensors firing, fire `EVENT_HOMEASSISTANT_STARTED` on the test bus; gate flips; subsequent `_run_inference` ticks dispatch normally.
- **Verify (timeout release):** with no census and no `EVENT_HOMEASSISTANT_STARTED`, advance test clock by `BOOT_SETTLE_TIMEOUT_SECONDS + 1`; the registered `async_call_later` callback flips the gate.
- **Test:** `test_boot_settle_release_via_real_inputs` — seed census > 0; assert release on the first tick.
- **Test:** `test_boot_settle_release_via_ha_started_event` — emit the event; assert release.
- **Test:** `test_boot_settle_release_via_timeout` — advance time; assert release.
- **Test:** `test_boot_settle_release_idempotent` — fire all three release paths in sequence; assert no duplicate "released" log lines and no double `async_dispatcher_send`.
- **Test:** `test_boot_settle_unsub_cleanup` — call coordinator unload; assert both `EVENT_HOMEASSISTANT_STARTED` listener and `async_call_later` are cancelled.
- **Sensor:** none new in v1 (avoid sensor proliferation per operator's `feedback_versioning_convention` discipline). Internal counter `_boot_suppressed_dispatches` exposed on the existing house-state sensor's `attributes` dict for live validation — REUSED pattern, mirrors `_wake_backstop_fires` attribute added in v4.7.18.1.
- **Live:** post-deploy, `sensor.ura_presence_coordinator_presence_house_state` exposes `boot_suppressed_dispatches: <int>` attribute. Value should be ≥1 on a cold boot, ≤4 (sanity ceiling: more would imply repeated suppression beyond the 60s window — a bug).

---

### D3: Boot-storm observability + failsafe instrumentation

**What.** Surface enough state on the existing house-state aggregate sensor that a future post-deploy validator can DETECT whether the gate worked, AND log a WARNING (not ERROR) if the timeout-release path fires (because that means Predicate A and the HA-started event both failed, which indicates either an empty-house cold boot — fine — OR a startup pathology worth knowing about).

**Files.**
- `domain_coordinators/presence.py` — add three attributes to whatever payload backs `sensor.ura_presence_coordinator_presence_house_state.extra_state_attributes`:
  - `boot_settle_done: bool`
  - `boot_settle_release_reason: str` — one of `"real_input"`, `"ha_started"`, `"timeout"`, or `"pending"`
  - `boot_suppressed_dispatches: int`
- `domain_coordinators/presence.py` — `_LOGGER.warning(...)` when `_timeout_release_boot_settle` is the actual releaser; `_LOGGER.info(...)` for the other two release paths.

**Bug-class guards.**
- Bug Class #44 (silent payload shape, v4.6.1.1 family): the three new attrs are simple JSON-serializable scalars; no nested dicts; no Optional dataclasses.
- Bug Class #14 (config snapshot staleness): attrs are computed on read, not cached.

### Acceptance Criteria

- **Verify:** at boot, the sensor attributes show `boot_settle_done: False, boot_settle_release_reason: "pending"`; after release, transitions to `True` + one of the three reasons.
- **Test:** `test_boot_settle_attrs_pending_at_start_real_input_on_release` — fresh coordinator, attrs show pending; trigger Predicate A; attrs show `real_input`.
- **Test:** `test_boot_settle_timeout_release_logs_warning` — assert `_LOGGER.warning` is called when the timeout path is the actual releaser (vs. INFO when Predicate A or B-event releases).
- **Live:** `boot_settle_release_reason == "real_input"` on most boots (expected — operator's house typically has census > 0 by ~30s post-restart from BLE seeding). If `"timeout"` is observed three boots in a row, that's a new investigation, not a fix.

---

### D4: Test fixture for cold-boot dispatch ordering

**What.** A reusable pytest fixture under `quality/tests/` that constructs a Presence Coordinator wired to a mock CM with no census and no zone trackers, then exposes hooks to advance time, fire `EVENT_HOMEASSISTANT_STARTED`, seed census, and capture `async_dispatcher_send` calls. Mirrors the v4.7.18.1 sleep-wake test patterns.

**Files.**
- `quality/tests/test_boot_settle_gate.py` — new file; ~150-200 LoC; ~6-8 tests as enumerated in D1-D3.

**Bug-class guards.**
- Per CLAUDE.md Tier 2-DB C-finding pattern: tests MUST drive the production code path (call `presence._run_inference(...)`); MUST NOT hand-construct INSERT statements or call `async_dispatcher_send` directly to "simulate" what the code should be doing. The captured-dispatcher pattern is the assertion surface; the production path is the driver.

### Acceptance Criteria

- **Test:** `pytest quality/tests/test_boot_settle_gate.py -v` runs green locally, in CI, and as a `@ura-validator` baseline-diff target.
- **Verify:** the fixture itself does NOT import or mock `homeassistant.components` (i.e., it works against the same minimal-HA shape the existing v4.7.18.1 tests use). If it can't, that's a fixture-authority-problem and the planner reviews before the builder forks new patterns.

---

## 4. Plan-completion accounting

### In scope for this cycle
- D1 — `_boot_settle_done` gate (Presence dispatch — Gate 1)
- **D1b — sibling `_boot_settle_done` gate on HVAC `_async_decision_cycle()` (Gate 2)** — added per the build-authorization decision below to cover scenario γ (§6).
- D2 — three-path release (Predicate A, EVENT_HOMEASSISTANT_STARTED, timeout) on BOTH gates
- D3 — sensor attributes + WARNING on timeout-release, including a `boot_settle_hvac_suppressed` counter so we can see which gate actually caught the storm
- D4 — pytest fixture + tests covering both gates

### Build authorization decisions (2026-06-04, operator)

The §4 open question and the §6 γ-risk were resolved by the operator at build authorization:

1. **Build BOTH gates, don't pick one.** Rather than build the Presence dispatch gate (Gate 1) and file the HVAC first-decision-cycle gate (Gate 2 / scenario γ) as a follow-up, build both now. Operator: *"Build both. Instrument it so we know which worked. And we can do a safe delete or prune after."*
   - **Instrumentation is the deciding factor:** `boot_settle_presence_suppressed` (Gate 1 count) and `boot_settle_hvac_suppressed` (Gate 2 count) are both surfaced on `sensor.ura_presence_coordinator_presence_house_state`. After a few cold boots the counts tell us which gate is load-bearing. If one gate's counter is reliably zero across boots, it is the prune candidate — a safe, evidence-driven deletion in a later cleanup cycle (NOT speculative removal now).
   - This converts the "necessary but not sufficient" risk in §6 into "belt and suspenders, measured" — we cannot ship blind to γ, and we don't have to guess which path dominates.
2. **Cold boot only (resolves the §4 open question — option (b)).** Both gates are born already-released when `hass.is_running` is True at `async_setup` (an options-flow reload, not a cold boot), recording `release_reason = "not_cold_boot"`. Only a genuine cold boot (`is_running` False) arms the suppression + the two Predicate-B release paths. This preserves reload responsiveness — an options save never delays actuation.

**Prune protocol (follow-up, not this cycle):** once live data from ≥3 cold boots shows one gate's suppressed-counter is consistently 0 while the other is >0, the zero gate may be removed in a dedicated cleanup hotfix. Until then, both stay — the redundancy is cheap (one bool check per first-tick) and the instrumentation is the whole point.

### Explicitly DEFERRED (with reasons)
- **`CONF_BOOT_SETTLE_SECONDS` user-configurable timeout.** Deferred to a follow-up cycle ONLY IF post-deploy live data shows the 60s default needs tuning. Operator convention: ship the constant first, configurability later (see `feedback_configurability_clarity`). Tracked in: post-deploy live observations; this doc.
- **Per-coordinator boot-settle gates on HVAC / Security / energy paths.** Deferred. Presence is the SOLE publisher of `SIGNAL_HOUSE_STATE_CHANGED`; if Presence holds the signal, downstream coordinators receive nothing to act on — that's the point. Adding the same gate on each subscriber would be duplicate defense. Re-evaluate ONLY if a Tier-2 review surfaces a non-house_state boot fan-out we missed.
- **HouseStateMachine restart-persistence.** REJECTED per operator decision 2026-06-03 (`DECISION_house_state_restart_persistence.md`). DO NOT re-propose in this cycle.
- **EC startup-race ("not_initialized" boot symptom).** Sibling, OUT of scope. Tracked: `project_ec_startup_race_evidence`.
- **Boot warning room-coordinators count (v4.7.18.2).** Already shipped. Not relevant.
- **Bayesian guest listener boot wiring (`__init__.py:1234`).** Read but NOT modified. The bayesian listener is one of the subscribers that benefits AUTOMATICALLY from Presence holding the signal. No direct change needed.
- **NEW `CONF_*` form fields anywhere.** Per the operator's "Number fields = form fields" rule (`feedback_plan_phrasing_number_fields`), this cycle ships ZERO new config-flow surface.
- **NEW Number entities, sensor entities, or buttons.** Reusing the existing house-state sensor's `extra_state_attributes` is sufficient.

### Open question — answer requested from operator before build
- **Should the boot-settle gate apply to the FIRST `SIGNAL_HOUSE_STATE_CHANGED` of every reload, or only the cold-boot one?** The current plan suppresses on every coordinator construction (both cold boot AND config-entry reload), because both go through `async_setup`. This may unintentionally swallow the dispatch on an options-flow save that triggers a reload. Two options for the builder:
  - **(a)** Always suppress on `async_setup` (current plan). Trade-off: an options reload that legitimately changes state may delay actuation by up to 60s.
  - **(b)** Differentiate via `hass.is_running` (`CoreState.RUNNING` already true → skip the gate entirely; the reload is happening while HA is up). Cleaner semantically; one more thing to test.

Recommend **(b)** — preserves reload responsiveness — but defer to operator. If unanswered before build, builder defaults to (b) and explicitly documents the choice.

---

## 5. Post-deploy live validation (feeds the validator agent)

After deploy + HA restart:
1. **Within 90s of restart:** `sensor.ura_presence_coordinator_presence_house_state` populates rich attributes (`boot_settle_done: True`, `boot_settle_release_reason: "real_input"|"ha_started"|"timeout"|"not_cold_boot"`, `boot_settle_presence_suppressed: N` (Gate 1 count), `boot_settle_hvac_suppressed: M` (Gate 2 count)). The two counters are how we tell which gate caught the storm.
2. **Within 90s of restart:** `journalctl -u home-assistant` shows zero "Setup timed out for stage 2" within the URA setup window. Pre-fix baseline: "Setup timed out for stage 2" appeared ~3-5 min post-restart on v4.7.19 and v4.7.20.1 boots.
3. **Within 3 min of restart:** MCP API responds (HTTP 200, not 000/timeout). Pre-fix baseline: 5-15 min CONNECTION_TIMEOUT.
4. **Within 5 min of restart:** at least one `SIGNAL_HOUSE_STATE_CHANGED` INFO log line for the FIRST real transition (away → home_day or similar), proving the gate releases cleanly.
5. **No regression:** `chain_house_state_*` chained automations still fire on subsequent legitimate transitions during the live session.
6. **WARNING-line check:** if `_LOGGER.warning("boot-settle: released via TIMEOUT ...")` is the actual releaser line three boots in a row, file a follow-up investigation (the gate is working but the release semantics are wrong — Predicate A is never firing on a normal boot).

If any of (1)-(4) fails: roll back per `feedback_deploy_discipline`.

---

## 6. Riskiest unknown the builder will hit

**The boot-storm root cause may not be a single `AWAY→HOME_DAY→AWAY` thrash.** It may be EITHER:
- **(α) The first real inference DOES dispatch a legitimate transition** (e.g., `AWAY → HOME_DAY` once census seeds), the chained automations on the OPPOSITE state (`chain_house_state_away`) DID NOT fire, but the storm comes from the `chain_house_state_home_day` chain — which the operator's HA YAML happens to wire to a `homeassistant.turn_off`-heavy actuation. In this case, suppressing the first dispatch DOES fix the storm but the operator's mental model ("away actuation") is slightly off.
- **(β) The storm is double-publish from an inference oscillation** (`AWAY → HOME_DAY → AWAY` within seconds because census transiently reads 0 again). In this case, the gate as designed suppresses BOTH dispatches and the world resolves silently into `HOME_DAY` on the third tick. Also fixed.
- **(γ) The storm is downstream of `SIGNAL_HOUSE_STATE_CHANGED` but not gated by it** — e.g., the HVAC decision-cycle that runs at `_async_decision_cycle()` immediately after Presence's `_ready_event.set()` (which fires REGARDLESS of dispatch suppression). If HVAC's first decision-cycle independently calls into preset overrides + fan turn_offs across all zones before any house-state dispatch ever fires, this gate does NOT fix that part.

The builder must verify which scenario(γ-risk) applies by inspecting:
- `domain_coordinators/hvac.py:485-555` (the `_async_decision_cycle()` call at `:555` runs unconditionally after Presence ready); and
- `domain_coordinators/hvac_fans.py:186-230+` (does the fan controller call turn_off on the first decision cycle for the AWAY state?).

If γ is the dominant path, the gate from D1-D3 is necessary but NOT sufficient and a SIBLING gate on HVAC's first decision cycle is required (file as a follow-up cycle, do NOT scope-creep into this one). The fastest way to know: builder pulls a journald excerpt from the next cold-boot showing the actual `light.turn_off` / `switch.turn_off` / `homeassistant.turn_off` call origins; if they trace to HA `automation.*` entities, the chained-automation path dominates and the plan is sufficient; if they trace to `urn:ha:service_call` from HVAC fan controller's internal turn_off, γ dominates and a sibling cycle is needed.

This is the single biggest unknown — flag it on the builder's intake, do NOT ship blind.
