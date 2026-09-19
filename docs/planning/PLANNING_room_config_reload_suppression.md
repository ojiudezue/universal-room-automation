# PLANNING — Room-config SAVE reload suppression (climate step)

**Card:** `ROOM-CONFIG-SAVE-FULL-RELOAD-STALL-1`
**Tier:** **2-DB** (reload path + shared substrate primitive, regression-prone;
follows the CM reload-suppression precedent).
**Status:** PLAN ONLY — awaits plan-review before any build.
**Author:** ura-planner
**Date:** 2026-09-19

---

## 0. Falsifiable invariant (state up front — D-reviewer falsifies)

> **INV-A (suppression correctness).** For every room-options SAVE whose
> `changed_keys` are all in the (extended) `_ROOM_SUPPRESS_KEYS` allowlist,
> the entry performs **zero** platform teardown / entity re-add (entity
> object identity is stable across the save) AND every consumer of every
> changed key reflects the new value on its next natural tick (no stale
> reads). Contrapositive: if any changed key has a CACHED consumer that
> is not paired with an in-place push in the suppress branch, the save
> MUST fall through to the full reload (INV-A must not be satisfied
> vacuously by admitting a stranded-cache key).
>
> **INV-B (substrate scope).** A SAVE on a single ROOM entry does not
> cause substrate work on OTHER rooms. Concretely: on the suppressed
> path, `OccupancySubstrate.refresh_subscriptions` fast-paths to its
> no-diff branch (no reset+seed for any room). No synthetic edge is
> dispatched for any other room. On the fall-through (full reload) path,
> only the reloading room's entities transit the substrate's
> add/remove/reclassify surface; sibling rooms see no listener churn.

Acceptance tests (D3) discriminate INV-A from a *vacuous* pass by
exercising both a live-read key (must suppress + consumer sees new value)
and a would-be-cached key (must fall through — not silently allowlisted).

---

## 1. Institutional context verified

### 1.1 Greps run + REUSE-or-BUILD per proposed piece

Every proposed change is a REUSE / EXTEND of existing machinery. No new
signal, sensor, helper, coordinator, or constant is proposed.

| Piece | Verdict | Existing at |
|---|---|---|
| ROOM options-update reload-suppression branch | REUSE (extend) | `__init__.py:7676-7715` (`_async_update_listener`, ROOM branch, `_ROOM_SUPPRESS_KEYS`) |
| Allowlist frozenset pattern (`_ROOM_SUPPRESS_KEYS`) | REUSE (extend membership) | `__init__.py:7660-7674` |
| In-place-push pattern for CACHED consumers | REUSE (mirror if needed) | `__init__.py:6393-6413` (`_NM_A2_KEYS`), CM branch `__init__.py:7725-7770`, `_EC_SETTER_DISPATCH` (grep hit) |
| Substrate re-subscribe signal on options_updated | REUSE (already dispatched) | `__init__.py:7700-7714`, `signals.py:199`, `presence.py:3333` handler |
| Substrate fast-path noop when entity set unchanged | REUSE (already exists — D2 leans on it) | `occupancy_substrate.py:436-442` (`if not added and not removed and not reclassified: return`) |
| Reload background-task dispatch (fall-through) | REUSE (unchanged) | `__init__.py:7616-7629` (docstring), fall-through below `_ROOM_SUPPRESS_KEYS` |
| `changed_keys` diffing via `room_last_applied_options` snapshot | REUSE (unchanged) | `__init__.py:7677-7685, 7723` |
| CONF constants referenced by allowlist expansion | REUSE (import from `const.py`) | see D1 field enumeration below |

**No NEW pieces.** Every proposed change is either (a) adding a constant
already imported to the existing frozenset, or (b) adding a per-key
in-place push mirroring `_NM_A2_KEYS`.

### 1.2 Prior planning / audit docs consulted

- `docs/planning/PLANNING_cm_reload_suppression*.md` (the pattern this
  cycle mirrors). Relevant: `_NM_A2_KEYS` push-vs-live-read taxonomy;
  the CM branch's `OPTIONS_RELOAD_SUPPRESS_KEYS` and its per-key audit
  comments are the template for D1's inline audit block.
- `docs/planning/PLANNING_onboarding_simplify.md` §D2/§D9 — cited at
  `config_flow.py:2575-2580`; confirms `CONF_WET_ROOM` is set once at
  room-create via `ROOM_TYPE_FEATURE_DEFAULTS`, so a wet-room *toggle*
  from the climate step is legal and expected to hit the suppress path.
- `docs/planning/PLANNING_hvac_demand_knobs_and_obs_gaps.md` (v5.103.8)
  — introduced `CONF_HVAC_VACANCY_HOLD[_NIGHT]` including the "blank =
  fall-through to type table" semantics (`config_flow.py:11694-11743`).
  The clearable-key semantics are load-bearing for D1's classification.
- `docs/reviews/PARENT_RELOAD_WATCHDOG.md` / memory
  [[feedback_parent_entry_reload_watchdog_hazard]] — same failure class
  at a different level (parent-entry reload cascade); this cycle is
  ROOM-entry only per non-goal N-2.

### 1.3 Memory bodies pulled

- [[project_cm_reload_suppression_cycle_stack]] — CM allowlist grew
  5→37 with per-key audit; RestoreEntity dropped for pushed keys; the
  no-reload proof was the sibling-`last_changed` invariant. That proof
  becomes D3's L1 live-validation test.
- [[feedback_parent_entry_reload_watchdog_hazard]] — reloading a
  parent-scope entry cascades → event-loop stall → watchdog ~5min. This
  cycle attacks the ROOM-scope analogue (~10-30s stall, no watchdog).
- [[feedback_coincidental_equality_masks_concept_split]] — hazard: a
  key may look live-read via `merged.get(...)` in one call site while
  being cached in another. D1 requires ALL consumers classified, not the
  first one found.
- [[feedback_do_robust_fix_not_bandaid_and_card]] — argues against
  carding a partial fix if the full expansion is doable. D1 policy:
  every climate-step key gets an explicit LIVE / CACHED / EXCLUDED
  verdict — no "we'll get to the rest later" residue.

### 1.4 Design docs read

- `docs/Coordinator/PRESENCE.md` — for `SIGNAL_ROOM_ENTRY_LIFECYCLE`
  handler ownership (PresenceCoordinator forwards to
  OccupancySubstrate).
- No IDENTITY/CAMERA scope in this cycle → IDENTITY_FUSION_CAMERAS_MANUAL
  not required.

### 1.5 Code locations surveyed end-to-end

- `custom_components/universal_room_automation/__init__.py:7616-7770`
  (the update listener, both ROOM and CM branches).
- `.../__init__.py:6393-6413` (`_NM_A2_KEYS`) and `:6822-6979`
  (`OPTIONS_RELOAD_SUPPRESS_KEYS`, `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`).
- `.../config_flow.py:2549-2707` (create-flow `async_step_climate`) and
  `:11432-11754` (options-flow `async_step_climate`) — the write source.
- `.../domain_coordinators/occupancy_substrate.py:351-529`
  (`refresh_subscriptions` + its fast-path noop at :436).
- `.../domain_coordinators/presence.py:3333` (lifecycle handler).
- Consumer files for each climate-step CONF listed under D1 will be read
  during the build's PRE-BUILD pass — see §D1 acceptance-consumer table
  columns (LIVE/CACHED verdict is REQUIRED per-key output of the build,
  not accepted as an assertion in this plan).

### 1.6 Prior-art scan verdict

**REUSE-only cycle.** Every mechanism this plan touches already exists.
Deliverables extend membership in an existing frozenset (D1) and lean on
the substrate's already-existing no-diff fast-path (D2). No new signal,
sensor, helper, config field, or state machine.

---

## 2. Problem (verified from logs 2026-09-19)

Operator saves a single toggle on the room "Climate & Fans" form. HA
becomes unresponsive ~10-30s. **No** HA restart. Log timeline shows:

1. Options-flow `async_step_climate` computes `merged = {**options,
   **user_input}` (`config_flow.py:11470-11493`) and calls
   `async_create_entry` → HA persists the entry and fires
   `_async_update_listener`.
2. `_async_update_listener` computes `changed_keys` via the snapshot
   diff (`__init__.py:7682-7685`). Because the climate step re-submits
   ~20 climate fields (fan-speed temps, `fan_temp_threshold`,
   humidity-fan knobs, `hvac_vacancy_hold[_night]`, targets, climate
   entity, etc.), and most are NOT in the current `_ROOM_SUPPRESS_KEYS`
   (only `CONF_ZONE`, comfort-temp min/max, comfort-humidity max,
   `fan_control_enabled`, `humidity_fan_control_enabled`), the subset
   test at `:7686` fails.
3. Fall-through fires the ROOM reload as a background task (~90 entities
   unload/re-add) plus the `SIGNAL_ROOM_ENTRY_LIFECYCLE` cascade natural
   to reload (unloaded → loaded), which drives
   `OccupancySubstrate.refresh_subscriptions`; the reload transiently
   removes-then-re-adds every occupancy entity of the changed room,
   which crosses the `added/removed` diff threshold at
   `occupancy_substrate.py:428-448`, and drives a full reset+seed for
   that room's buckets. Sibling-room warnings observed in logs stem
   from the substrate's synthetic-edge dispatch during the transient
   remove-then-re-add window.
4. Net effect: a save that only meant to flip one boolean cycles
   platform setup for ~90 entities on the event loop, blocking other
   coroutines for the observed 10-30s window.

**Root cause (verified against code):** `_ROOM_SUPPRESS_KEYS` covers
only 5 keys today; the climate step writes ~20; the subset check almost
always fails.

**Non-cause (verified):** substrate `refresh_subscriptions` itself is
cheap on the *suppressed* path (fast-path noop at `:436`). The stall is
driven by the full reload, not by the substrate signal.

---

## 3. Deliverables

Two deliverables. D1 is the crux. D2 is a scope-check + minimum-safe
reduction; the full per-room substrate re-claim is parked.

### D1 — Extend `_ROOM_SUPPRESS_KEYS` to climate-step keys, per-key proven safe

**File:** `custom_components/universal_room_automation/__init__.py`
(only `_ROOM_SUPPRESS_KEYS` at `:7660-7674` and, if any key requires it,
a small in-place push block above the `return` at `:7715`).

**Pre-build enumeration (build output, plan asserts the shape only).**
The builder reads `config_flow.py:async_step_climate` (both create at
`:2549-2707` and options at `:11432-11754`) and produces the EXACT
field list — no key may be guessed. From the read above (§1.5) the
climate-step submitted keys are (audit-table columns to be filled by the
builder before adding any key to the allowlist):

| CONF key | Source line | LIVE / CACHED / EXCLUDED | Consumers (file:line) | Verdict |
|---|---|---|---|---|
| `CONF_HVAC_COORDINATION_ENABLED` | `config_flow.py:2599, 11524` | TBD | TBD | TBD |
| `CONF_FAN_CONTROL_ENABLED` | `:2600, 11528` | **LIVE (already allowlisted)** | see `__init__.py:7665-7673` audit | KEEP |
| `CONF_COMFORT_FAN_AWAY_VETO_ENABLED` | `:2606, 11532` | TBD | TBD | TBD |
| `CONF_HUMIDITY_FAN_CONTROL_ENABLED` | `:2610, 11540` | **LIVE (already allowlisted)** | see `__init__.py:7665-7673` audit | KEEP |
| `CONF_WET_ROOM` | `:2613, 11547` | TBD | TBD | TBD |
| `CONF_BLE_HOLD_CAP_ENABLED` | `:2615, 11550` | TBD | TBD | TBD |
| `CONF_HUMIDITY_FAN_SPIKE_ENABLED` | `:2618, 11557` | TBD | TBD | TBD |
| `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_ENABLED` | `:2621, 11561` | TBD | TBD | TBD |
| `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_BASE_S` | `:2624, 11567` | TBD | TBD | TBD |
| `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_PER_MIN_S` | `:2630, 11576` | TBD | TBD | TBD |
| `CONF_HUMIDITY_FAN_PRESENCE_RUNTIME_CAP_S` | `:2636, 11585` | TBD | TBD | TBD |
| `CONF_FAN_TEMP_THRESHOLD` | `:2641, 11594` | TBD | TBD | TBD |
| `CONF_HUMIDITY_FAN_THRESHOLD` | `:2644, 11618` | TBD | TBD | TBD |
| `CONF_HUMIDITY_FAN_TIMEOUT` | `:2647, 11624` | TBD | TBD | TBD |
| `CONF_HUMIDITY_FAN_MAX_RUNTIME` | `:2650, 11630` | TBD | TBD | TBD |
| `CONF_HUMIDITY_FAN_SPIKE_DELTA_PCT` | `:2657, 11638` (advanced) | TBD | TBD | TBD |
| `CONF_HUMIDITY_FAN_SPIKE_EMA_ALPHA_S` | `:2663, 11647` (advanced) | TBD | TBD | TBD |
| `CONF_HUMIDITY_FAN_SPIKE_BASELINE_MODE` | `:2669, 11656` (advanced) | TBD | TBD | TBD |
| `CONF_FAN_SPEED_LOW_TEMP` | `:2719, 11600` | TBD | TBD | TBD |
| `CONF_FAN_SPEED_MED_TEMP` | `:2722, 11606` | TBD | TBD | TBD |
| `CONF_FAN_SPEED_HIGH_TEMP` | `:2725, 11612` | TBD | TBD | TBD |
| `CONF_TARGET_TEMP_HEAT` | `:2685, 11677` | TBD | TBD | TBD |
| `CONF_TARGET_TEMP_COOL` | `:2688, 11683` | TBD | TBD | TBD |
| `CONF_CLIMATE_ENTITY` | `:2692, 11689` | TBD | TBD | TBD |
| `CONF_HVAC_VACANCY_HOLD` | `:11720` | **CACHED-suspected — resolved via `hvac_zones.py:_effective_hvac_hold_seconds`; verify it reads `entry.options` per-call** | TBD | TBD |
| `CONF_HVAC_VACANCY_HOLD_NIGHT` | `:11733` | as above | TBD | TBD |

**Classification rules (unchanged from CM precedent):**
- **LIVE-READ** → readers pull `entry.options` / `entry.data` /
  `merged.get(...)` on every tick or every decision (grep evidence:
  `_read_per_room_*`, `entry.options.get(CONF_*)`, no in-memory cache
  copied at setup). Safe to bare-suppress: add to frozenset.
- **CACHED** → value is copied to `self.<attr>` at coordinator setup
  and only refreshed on reload. NOT safe to bare-suppress. Two legal
  outcomes:
  - **EXCLUDED** (preferred): leave OUT of frozenset. The key still
    triggers a full reload — documented in the audit comment as
    "cached; excluded from suppression to avoid stale-attr drift."
  - **PUSH-IN-PLACE** (only if trivial): mirror `_NM_A2_KEYS`
    pattern — in the suppression branch, before the `return` at
    `__init__.py:7715`, dispatch the CONF-specific setter that
    updates the cached attr on the live coordinator instance. Only
    acceptable when the setter is one-line and idempotent.
- **default = EXCLUDED**. A key whose consumer set the builder cannot
  fully enumerate stays EXCLUDED. The builder does NOT allowlist on
  suspicion.

**Consumers to grep for each key** (surfaces, non-exhaustive — the
builder greps ALL of them):
- `custom_components/universal_room_automation/coordinator.py`
- `sensor.py`, `binary_sensor.py`, `switch.py`, `number.py`,
  `select.py`, `button.py`, `time.py`
- `domain_coordinators/*.py` (esp. `hvac_zones.py`, `presence.py`,
  `energy.py`, `optimization*.py`)
- `automation.py`, `actuator_reconciler.py`, `fan_veto.py`,
  `room_classification.py`, `memory_facade.py`,
  `binary_sensor_control_attrs.py` (grep hits from §1.5 pre-scan)

**Audit-comment style:** MIRROR the existing block at
`__init__.py:7642-7659` (CONF_ZONE audit) and `:7665-7673`
(fan-toggle audit). Each newly-allowlisted key gets 3-6 lines: the
consumer file:line list, the reason it's LIVE, and a one-liner on
what would flip it to CACHED (so a future refactor that introduces
a cache is caught by re-reading the audit block).

**Non-goals inside D1:**
- No new CONF keys.
- No refactor of any consumer from CACHED → LIVE. If a key is CACHED
  and the push is non-trivial, EXCLUDE it — do not rewrite the
  consumer in this cycle.
- No change to the create-flow write path (it uses `_data.update()`
  and finalizes in `async_step_notifications`, not `async_step_climate`
  directly — see `:2582-2584`; the create flow is out of scope: on
  create, a full setup runs anyway).

### D1 Acceptance Criteria (discriminating)

- **Verify (INV-A pass, suppression happens):** A toggle of one
  LIVE-READ climate boolean (e.g. `CONF_COMFORT_FAN_AWAY_VETO_ENABLED`
  once its LIVE verdict is proved) produces a single log line
  `"ROOM options changed for '<room>' … suppressing reload
  (changed_keys=[CONF_COMFORT_FAN_AWAY_VETO_ENABLED])"` and **zero**
  `"Setting up universal_room_automation"` / platform setup lines for
  that entry within 30s of save.
- **Verify (INV-A discriminator: stale-cache NOT admitted):** A change
  to any key classified CACHED-EXCLUDED (e.g., if
  `CONF_HVAC_VACANCY_HOLD` classifies CACHED) causes the fall-through
  reload — log line `"ROOM options changed … suppressing reload"` MUST
  NOT appear for that save. A test that suppresses a CACHED-EXCLUDED
  key is a FAIL, not a pass.
- **Verify (consumer freshness):** For each newly-allowlisted key, a
  behavioral test toggles the value in `entry.options`, does NOT
  reload, and asserts the next coordinator tick / next entity update
  reads the new value. Test authority = source-mutation: neuter the
  live-read at the consumer, prove that ONE specific test fails, then
  restore (Tier 2-DB Review C convention).
- **Entity identity-stable:** For any key in the extended allowlist,
  entity-object `id()` for a sampled room-scoped entity is identical
  before and after the save (proves no teardown/re-add).
- **Sensor:** `sensor.<room>_active_holds` (or another live per-room
  sensor) shows `last_changed` unchanged on sibling rooms across the
  save.
- **Test:** `quality/tests/test_room_options_reload_suppression.py`
  (extend or add) — one test per newly-allowlisted key; plus one test
  per key intentionally EXCLUDED asserting fall-through.
- **Live (post-restart):** Save a real climate-step form on one room
  with only a live-read toggle changed; observe (a) no "Setting up"
  log for that entry, (b) no sibling-room substrate re-claim warning,
  (c) HA UI remains responsive (subjective, but ≤2s stall vs
  baseline 10-30s).

### D2 — Scope the substrate re-subscribe to the changed room (minimum-safe)

**Finding first (pre-D2 read, verified §1.5).** The substrate ALREADY
has a fast-path noop when the observed entity set doesn't diff
(`occupancy_substrate.py:436-442`). On the **suppressed** path,
`SIGNAL_ROOM_ENTRY_LIFECYCLE` fires with reason `"options_updated"`,
`refresh_subscriptions` runs, `_discover_entity_map()` returns the SAME
entities (no CONF list changed — the CONF sensor lists are NOT in the
suppress allowlist and remain a fall-through), so `added / removed /
reclassified` are all empty and the method returns at `:442` without
touching any room bucket.

**⇒ D1 SUBSUMES most of D2's original scope.** Once D1 ships, the
substrate work on a climate-only save is a single `_discover_entity_map`
walk (O(entities), no I/O, no dispatch). No per-room-scoping refactor
of the substrate is required for the reported symptom.

**Residual D2 (this cycle):** on the **fall-through** path (a CACHED
key changed and forced the reload), the substrate DOES see transient
remove+re-add of the reloading room's entities, and its
synthetic-edge dispatch at `:502-529` re-emits edges for that room.
That is correct behavior (the entities really did go away and come
back), but the log noise reads as "house-wide re-claim." The minimum
safe reduction:

**D2 deliverable:** Change the substrate's log message at
`occupancy_substrate.py:444-448` to include the SET of room names
whose buckets were touched (currently only counts are logged), so that
in the fall-through case the log is unambiguously scoped to the one
reloading room — killing the "sibling re-claim" misread. Keep the
diff semantics unchanged.

**Parked (do NOT build this cycle) — carded separately:**
- Per-room `refresh_subscriptions(entry_id=…)` variant that only
  re-discovers the changed room's entities. Rationale for parking:
  (a) invariant on multi-room-claim arbitration ("claimed by multiple
  rooms" dedup) requires the substrate to see the FULL desired entity
  set to detect a claim overlap — a scoped refresh has to re-derive
  the dedup either way; (b) D1 already eliminates ~100% of the
  reported user-visible stall path (climate-step saves), so the
  marginal benefit of per-room scoping is low against the ripple
  risk in the dedup path. Card: `SUBSTRATE-PER-ROOM-REFRESH-1`
  (new, this plan proposes it; not in scope for build).

### D2 Acceptance Criteria (discriminating)

- **Verify (INV-B pass, suppressed path):** On a climate-step save
  whose changed_keys ⊂ (extended) `_ROOM_SUPPRESS_KEYS`, log
  `"OccupancySubstrate.refresh_subscriptions: no diff — noop"`
  appears exactly once and **no** `"emitted N True-edge …"` line
  appears. Sibling-room synthetic-edge dispatch count = 0.
- **Verify (INV-B, fall-through path — discriminator):** On a
  fall-through save (CACHED-EXCLUDED key changed), the substrate log
  identifies the reloading room by name; no sibling room name appears
  in the touched-room list.
- **Test:** unit test on `refresh_subscriptions` that installs a
  known entity map, fires the signal with no CONF change, and
  asserts the no-diff branch is taken (dispatch counter == 0).
- **Live:** climate-step save on a LIVE-READ key produces zero
  substrate `emitted …` log lines cluster-wide.

---

## 4. Knob ladder — numbers-get-knobs audit

**Zero new knobs proposed.** Every value in scope is already a CONF or
frozenset membership decision:

| Value | Rung today | Change this cycle |
|---|---|---|
| `_ROOM_SUPPRESS_KEYS` | Module constant (frozenset in `__init__.py`) | EXTEND membership. Correct rung — this is safety-adjacent (a bad allowlist strands cached consumers); belongs behind code review, not operator-tunable. |
| Each climate-step CONF | Options-flow field | UNCHANGED |
| Substrate diff thresholds | N/A (structural) | UNCHANGED |

Rationale: adding a runtime toggle to suppress reload would be a
**footgun knob** (an operator who flips it wrong strands cached state
until the next natural reload). Correct rung is module constant.

---

## 5. Non-goals

- **N-1.** The concurrent Shelly / Tuya / Bond network-timeout storm
  observed in the same log window is a separate integration issue and
  not URA. Not in scope.
- **N-2.** The parent / CM entry reload path is unchanged. This cycle
  is ROOM-entry only (`entry_type == ENTRY_TYPE_ROOM` branch).
- **N-3.** No refactor of any CACHED consumer into LIVE-READ (see D1
  non-goal above). Refactors are individually valuable but each has
  its own ripple; carded separately if a specific consumer becomes a
  stall path.
- **N-4.** No per-room substrate scoping refactor (parked as
  `SUBSTRATE-PER-ROOM-REFRESH-1`; see D2).
- **N-5.** No change to the options-flow UI or the climate-step field
  set.
- **N-6.** No change to the create flow — a new-room create runs full
  platform setup by design.
- **N-7.** No change to the fall-through reload's background-task
  dispatch behavior (v4.0.5 fix at `:7619-7624` remains).

---

## 6. Review plan (Tier 2-DB — three framing-disjoint reviewers)

Per `CLAUDE.md` §Tier 2-DB. Standing policy: three disjoint framings.

- **Reviewer A — data integrity + consumer-classification correctness.**
  Re-runs the full grep for EVERY climate-step key across ALL surfaces
  in §D1 consumer list; independently classifies LIVE/CACHED; compares
  to the builder's table. Any disagreement = HIGH finding. Verifies
  that no key was allowlisted on the strength of ONE call site while
  another site cached it (concept-split hazard).
- **Reviewer B — migration correctness + signal chain.** Verifies the
  `SIGNAL_ROOM_ENTRY_LIFECYCLE` dispatch on the suppressed path
  reaches `refresh_subscriptions` and short-circuits at
  `occupancy_substrate.py:442`. Verifies fall-through path preserves
  the v4.0.5 background-task semantics. Verifies snapshot reseed at
  `:7723` still fires on the fall-through so the NEXT save diffs
  correctly.
- **Reviewer C — test authority via source mutation.** For each key
  the builder adds to the allowlist, C edits the production consumer
  source to neuter its live-read (return the stale value), runs the
  suite, asserts a SPECIFIC test fails, restores. A key whose neuter
  leaves the suite green is not really tested — HIGH finding, block
  ship. Verifies bytecode-cache discipline
  ([[feedback_mutation_verification_pycache_staleness]]).

**Optional D — adversarial completeness.** Not mandatory for Tier 2-DB
but recommended given the shared-primitive (substrate) touch. D's job:
state INV-A and INV-B as falsifiable, then break them. Concrete
targets: (a) find a climate-step key that reaches a CACHED consumer via
a path A/B/C didn't grep; (b) construct a legal-config sequence where
INV-B fails (substrate touches a sibling room on a suppressed save).

**Plan-review (before build).** This document itself goes to ONE
adversarial plan reviewer per Tier 2 plan-review policy. The reviewer
re-greps the D1 field enumeration against `config_flow.py:2549-2707`
and `:11432-11754` to confirm no key is missing, and re-verifies each
already-classified entry in §D1's table (the "already allowlisted"
LIVE claims for `CONF_FAN_CONTROL_ENABLED` and
`CONF_HUMIDITY_FAN_CONTROL_ENABLED`).

---

## 7. Pre-deploy zero-bugs gate

Per [[feedback_pre_deploy_zero_bugs_gate]]:

- `grep '<<<<<<<'` on the diff — no conflict markers.
- `py_compile` on `__init__.py` and `occupancy_substrate.py`.
- Cycle tests: `pytest quality/tests/test_room_options_reload_suppression.py -v`.
- Suite-baseline-diff vs `pre-review-vX.Y.Z` — name-diff (not count).
- Independent orchestrator verification: re-grep `_ROOM_SUPPRESS_KEYS`
  membership vs the climate-step field list — the builder's audit
  table is a hypothesis until the orchestrator re-runs the grep.

---

## 8. Live validation (README write-back — MANDATORY)

Post-deploy, the `README_v<version>.md` prospective bullets get
replaced with a `Validated <date>` table:

| Criterion | Result | Evidence |
|---|---|---|
| Live-read toggle save produces suppress log | TBD | log line `"ROOM options changed … suppressing reload"` cite |
| No platform setup lines for entry within 30s | TBD | `journalctl -u home-assistant … --since` scan cite |
| CACHED-EXCLUDED key save still reloads | TBD | log cite + entity-id change confirmed |
| Consumer sees new value on next tick | TBD | entity attribute read pre/post save |
| Substrate no-diff noop on suppressed path | TBD | `"no diff — noop"` log cite |
| No sibling-room substrate emit lines | TBD | grep of substrate log |
| HA UI responsive across save (~subjective) | TBD | operator observation |

---

## 9. Plan-completion tracking

Items planned in this doc that will be tracked to completion at cycle
close (§ per CLAUDE.md "Plan Completion Tracking"):

1. D1 audit table filled in for EVERY climate-step key (LIVE / CACHED
   / EXCLUDED verdict + consumer cites). No TBD rows at ship.
2. Every LIVE key added to `_ROOM_SUPPRESS_KEYS` with inline audit
   comment mirroring `:7642-7673` style.
3. Every CACHED-EXCLUDED key documented in the audit block (why
   excluded, what would flip it).
4. D2 log-message change shipped OR explicitly parked with a card.
5. Card `SUBSTRATE-PER-ROOM-REFRESH-1` created (parked) with the
   dedup-invariant rationale from §D2.
6. README validation table written back post-live-validation.

Any deferred item is explicitly named in the ship note with reason and
card ID — no silent drops.

---

## 10. Risk register (short)

- **R-1 (HIGH):** A consumer misclassified LIVE (actually CACHED)
  strands stale state on the suppressed path. Mitigation: Reviewer A
  independent re-classification + Reviewer C per-key source-mutation
  test.
- **R-2 (MED):** A climate-step key missing from the enumeration
  table (schema drift between plan and build). Mitigation:
  plan-reviewer re-greps the schema; builder writes the enumeration
  table BEFORE editing `_ROOM_SUPPRESS_KEYS`; orchestrator verifies.
- **R-3 (MED):** Snapshot reseed at `:7723` skipped by a control-flow
  slip during the D1 edit. Mitigation: Reviewer B checks; test
  covers "second save after fall-through diffs correctly."
- **R-4 (LOW):** D2 log change accidentally alters diff logic.
  Mitigation: change is confined to the log format-string; diff-only
  review.
- **R-5 (LOW):** The clearable-key semantics for
  `CONF_HVAC_VACANCY_HOLD[_NIGHT]` interact with the snapshot diff
  (unset → present transitions). Mitigation: build enumerates the
  clearable case in the test matrix.
