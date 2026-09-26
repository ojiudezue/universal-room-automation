# PLANNING — W2 HVAC Occupancy Fast Path (shave the 5-min tick)

**Card:** `HVAC-W2-OCCUPANCY-TRUTH` (child: `HVAC-HOT-ENTRY-LATENCY-1`).
**Workstream:** W2 (Occupancy Truth), from the operator-approved 4-workstream HVAC arc.
**Design origin:** commit `82620357a` (fast-in cannot beat `HVAC_DECISION_TICK`; needs an event-driven path); prior context in `docs/planning/PLANNING_hvac_zone_conditioning_demand.md` and `docs/planning/PROPOSAL_hvac_conditioning_demand_2026_09_16.md`.
**Operator scope (2026-09-26, binding, §9d of the state-of-play):** *"The HVAC signaling from rooms that is more immediate I expect to shave the 5m tick only for now."* A room/zone HVAC-occupancy change triggers a **rate-limited per-zone** decision cycle so HVAC no longer waits up to one `HVAC_DECISION_TICK` (5 min). **NOTHING else changes** — entry dwell stays 2 min; no hold/grace/tail/override/retreat-semantics change; whole-house cycle unchanged; presets-only writes unchanged.
**Sequencing:** BUILD AFTER `feature/hvac-live-room-establishment` (v5.103.15) merges — this plan edits `hvac.py` in the same regions that branch is still churning (subscribe block :1131-1213, `_async_decision_cycle` :1564, `_run_decision_cycle` :1600). Flagged overlap in D2 wire-in.

---

## 0. MANDATORY READ CONFIRMATION

Planner has read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely — §0 owner rule, §2 decision-loop table (confirms no room-occupancy trigger exists on `develop`; only HOUSE_STATE / ENERGY_CONSTRAINT / PERSON_ARRIVING / SAFETY_HAZARD / ZM_ZONES_UPDATED at `hvac.py:1131-1213`), §3.1/§3.2 occupancy model, §3.2 dwell 2 min at `hvac.py:2355-2368`, §5 Carrier status vs config feed, §7 lockout, §9.1 self-lockout, §9.5 hot-entry latency, §9d W2 scope decision, §10 C8/C10/C11, §11 arc (W2 sits after W1-A; this is a W2 step). Any conflict with the state-of-play is a bug in this plan; fix here before build.

---

## 1. Institutional context verified

### 1.1 Prior-art scan — REUSE-or-BUILD per proposed piece (three surfaces)

| Proposed piece | Verdict | Existing symbol (file:line) — or NEW because |
|---|---|---|
| Decision-cycle trigger (dispatcher OR state-listener) | **REUSE pattern** | Existing triggered cycles use `self.hass.async_create_task(self._async_decision_cycle())` tracked in `self._pending_tasks` — house-state at `hvac.py:3131-3133`; pre-arrival at `hvac.py:4002-4004`; boot-settle at `hvac.py:1539-1547` (via `async_call_later`, unsub on `_unsub_listeners`). Re-entrancy already covered by `self._decision_cycle_lock` at `hvac.py:1592-1598`. |
| Signal carrying per-room `hvac_occupied` transitions | **NEW (thin)** | No such signal exists. Greps of `domain_coordinators/signals.py`, `hvac_zones.py`, `hvac.py`, `coordinator.py`, `binary_sensor.py`: no `SIGNAL_*OCCUPANCY*` for rooms; `SIGNAL_ROOM_ENTRY_LIFECYCLE` (signals.py:199) is about entry loaded/unloaded, not occupancy. `HVACOccupiedBinarySensor` (`binary_sensor.py:745`) is a lazy read-only mirror of `ZoneManager` state and updates only when the room coordinator pushes. Two REUSE options considered below. |
| Producer refresh outside the 5-min tick | **REUSE (extend)** | `ZoneManager.update_room_conditions` (`hvac_zones.py:523`) is the ONLY producer of `RoomCondition.hvac_occupied`; today called at setup (`hvac.py:1254`) and inside the tick (`hvac.py:1647`). Extend by calling from the fast-path trigger BEFORE the decision cycle runs (same method, unchanged behaviour — no new producer). |
| Rate-limiter primitive | **NEW (module const + per-zone `dict[str, datetime]`)** | No existing per-zone throttle in `hvac.py` matches "min interval between triggered cycles." `_pending_tasks` is a set for lifecycle only. Nudge/hard-reset budgets in `hvac_override.py` are per-day count budgets, wrong shape. Model on `HVAC_DECISION_TICK` (`hvac_const.py:11-13`) — rung-1 module const, cloud-call-rate bound. |
| Follow-up cycle after dwell expiry | **REUSE pattern** | `async_call_later` + append unsub to `self._unsub_listeners` (identical to boot-settle kickoff at `hvac.py:1544-1547`; identical to egress force-release at `hvac.py:1406-1408`). Per-zone dedup dict (NEW, one line). |
| Teardown-safety | **REUSE** | All timer unsubs already routed through `self._unsub_listeners`, drained by `_cancel_listeners` in `async_teardown` (Bug Class #50 pattern; suppression-needs-a-discharge). |
| Hallway exclusion at trigger | **REUSE** | `_compute_hvac_occupied` at `hvac_zones.py:650-665` (`arm_source="hallway_excluded"`); `CONF_ROOM_TYPE == ROOM_TYPE_HALLWAY` (const.py). Read the same field at the listener to skip. |
| Zone-membership lookup (room → zone) | **REUSE** | Same iteration pattern used in `binary_sensor.py:908-910` (`for zone in zm.zones.values(): if room_name in zone.rooms`). |

### 1.2 Prior planning docs consulted

- `docs/planning/PLANNING_hvac_zone_conditioning_demand.md` (full skim) — defines D1 producer, D2 sibling sensor, D5 zone-dwell handling; the fast path is the explicit missing "step 5" it names but did not build.
- `docs/planning/PROPOSAL_hvac_conditioning_demand_2026_09_16.md` (skim) — the design proposal that carries `82620357a`'s "HVAC_DECISION_TICK is a hard floor" statement and enumerates the fast path as conditional.
- `docs/planning/PLANNING_hvac_live_room_establishment.md` REV 2 (headers + affected regions) — v5.103.15 in flight; shares files with this plan (see §7 overlap flag).
- `docs/planning/PLANNING_hvac_governed_excursion.md` rev-6 (skim) — reason the trigger MUST route through `_async_decision_cycle` (lease/backstop rules already live there); do not bypass to `_run_decision_cycle`.
- Kanban cards read from `docs/planning/kanban.data.yaml`: `HVAC-W2-OCCUPANCY-TRUTH` (`operator_decisions_2026_09_26`, `fast_path_planning_2026_09_26`), `HVAC-HOT-ENTRY-LATENCY-1` (`entry_dwell_finding_2026_09_25`, root_cause = 5-min tick + dwell). Note C11 in state-of-play (§10): the 09-26 operator turn set dwell live to **2 min**, so residual hot-entry cost is dwell (≤2 min) + up to one 5-min tick = **up to ~7 min**; the fast path shaves the second term.

### 1.3 Memory bodies pulled

- `reference_code_tracing_methodology.md` — producer→entry/exit→consumers→cross-cycle. Applied to the trigger signal in §4.
- `feedback_wire_in_anchor_mandatory.md` — every builder brief demands enclosing-method behavioural anchor + call-neuter drill; wire-in anchors in §5.
- `feedback_suppression_needs_discharge.md` — the rate-limiter is a suppression; must specify what re-fires it + backstop + restart survival. Answered in §4.3.
- `feedback_measure_before_build.md` — a one-shot recorder probe over existing data is D0 here (§3), not a runtime probe.
- `feedback_marginal_benefit_pushback.md` — decomposed in §2. Simplest version = rising-edge-only fast path; the dwell-expiry follow-up is small marginal cost, real marginal benefit; the per-zone (vs whole-house) trigger is deferred (see §6 open question).
- `feedback_tier2plus_prior_art_scan.md` — this plan's §1.1 is the required scan; reviewer must re-grep.
- `project_incident_v5_8_0_setup_recursion.md` — reload-storm hazard on setup paths; §5 D3 accounts for it.

### 1.4 Design docs read

- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — MANDATORY, done. Specifically §2 (verified no fast path today), §3.1/3.2 (occupancy model + dwell mechanics), §4 (write funnels), §7 (lockout — this plan writes nothing new; it just runs the existing decision cycle earlier), §9d (scope decision), §11 (W2 sits after W1-A).

### 1.5 Code locations surveyed (read end-to-end during scoping)

- `hvac.py`: subscribe block :1131-1213; periodic timer + kickoff :1355-1363; `_release_boot_settle` :1510-1552; `_async_decision_cycle` :1564-1598; `_run_decision_cycle` :1600-1700 (update_room_conditions call :1647); zone dwell :2355-2368; `_handle_house_state_changed` :3096-3133; `_handle_person_arriving` :3990-4004.
- `hvac_zones.py`: `update_room_conditions` :523; hallway-excluded arm :650-665; `_hvac_seen.add` :988; `is_zone_hvac_established` :1043; `conditioning_retreat_ok` :1085.
- `hvac_const.py`: `HVAC_DECISION_TICK` :11-13 (rung-1 module const).
- `binary_sensor.py`: `HVACOccupiedBinarySensor` :745-919; per-room slug + zone lookup pattern :906-919.
- `domain_coordinators/signals.py`: full read — no per-room occupancy signal exists.
- `coordinator.py`: STATE_OCCUPIED write sites (67 refs); confirms room coordinator is where lighting-fused occupancy lands (Override switches applied :4791-4811).

---

## 2. Falsifiable invariant

**INV:** *"For every HVAC-occupancy rising edge on a live, non-hallway room R (room-type != `ROOM_TYPE_HALLWAY`, ROOM config entry LOADED, coordinator present) belonging to zone Z, a `_run_decision_cycle` invocation reads `update_room_conditions`-refreshed state for R AND completes within `FAST_PATH_SLA_S` (target: 10 s) of the state-change event, EXCEPT when the per-zone rate limiter denies the trigger; AND the per-zone triggered-cycle rate is ≤ `HVAC_FAST_PATH_MIN_INTERVAL_S`⁻¹ over any 5-min window; AND `_unsub_listeners` teardown cancels every fast-path timer/subscription in the same envelope as the periodic timer (no orphan tasks, no writes after unload)."*

Discriminating observations required (a fix vs a plausible other failure must produce different rows):
- Fast-path fires but cycle lock re-entrant → visible in a new `fast_path_reason` field on the decision-log row (`skipped_reentrant` vs `ran` vs `rate_limited`).
- Fast-path fires but dwell-suppressed → the row records `dwell_active_ms_remaining`, and D2's dwell-expiry follow-up produces a *second* row with `fast_path_reason=dwell_followup`. Absence of the second row within `dwell_ms + slack` = defect.
- Rate limiter denied → NM LOW `hvac_fast_path_rate_limited` (per-zone, dedup by engagement-id per 5 min).

Adversarial (Reviewer D) job in Tier 2-DB: falsify INV. Candidate breaks to enumerate: hallway-only zones; a room whose coordinator is loading (v5.103.15's "transient blocks"); dwell in progress when trigger fires (D2 follow-up must fire); trigger during boot-settle suppression; trigger while `_egress_manager` initial-restore gate holds; trigger during a reload storm (v5.103.15 §9.4 hazard); teardown mid-`async_call_later`; the second edge inside limiter window (must NOT drop the observation — see §4.3).

---

## 3. D0 — Measure before you build (READ-ONLY, ~30 min)

**Purpose:** size the rate limiter empirically from the current install; refuse to build with a guessed value.

**Probe:** one-shot Python over `/config/home-assistant_v2.db` via `ssh ha "python3 -" < probe.py` — no runtime code, no HA restart.

**Signals to query (30 days retention window):**
1. Rising edges per day per **room** on `binary_sensor.<room>_<room>_hvac_occupied` (~43 entities; §3.1 of state-of-play).
2. Rising edges per day per **zone** = OR-fold over the zone's rooms → count of "zone had 0 hvac-occupied rooms, then had ≥1" transitions. This is the true fast-path trigger rate.
3. Fallback if (1) is sparse (v5.103.8 entities not enabled long enough): use `binary_sensor.<room>_<room>_occupied` (lighting-fused; rising edges are a strict upper bound because hvac_occupied has tail-hold on the falling edge, not the rising edge).
4. p50 / p95 / p99 gap between consecutive rising edges per zone (seconds).
5. Distribution of within-5-min bursts per zone per day (how often ≥2 rising edges land inside one existing tick).

**Acceptance for D0:**
- Report committed to `docs/planning/AUDIT_hvac_fast_path_rate_2026_09_26.md` before D2 dispatch.
- Table: per-zone daily edge count (median / p95 / max), inter-edge gap p50/p95/p99, bursts-per-5-min p95.
- **Sizing rule:** `HVAC_FAST_PATH_MIN_INTERVAL_S` chosen so that at p99 daily burst rate the limiter denies < 10% of triggers per zone. If p99 already ≤ 1 trigger per 60 s per zone, start at **60 s**; if p99 is denser (e.g. hallway-adjacent rooms flapping), pick from the measured distribution.
- If a zone's daily rate is < 6 rising edges (i.e. the fast path adds <6 cycles/day beyond the existing 288 ticks) the limiter is a headroom guard, not a rate governor — say so.

**Fail-out:** if D0 shows the probe cannot distinguish rising edges from restart-storm artifacts (v5.103.15 §9.4), stop and card that first — the fast path would amplify the storm.

---

## 4. Design

### 4.1 Trigger source — decision + code cite

**DECISION:** subscribe HVAC to HA `state_changed` events for a **filtered set of entities**: the per-room lighting-fused occupancy binary sensors (`binary_sensor.<room>_<room>_occupied`) whose owning ROOM entry has `CONF_ROOM_TYPE != ROOM_TYPE_HALLWAY`, using `async_track_state_change_event` (already imported at `hvac.py:25`). Rising edge only (see §4.2).

**Why not a new signal from `ZoneManager`?** Considered and rejected for the initial ship: `update_room_conditions` is called only from the decision cycle itself (`hvac.py:1254`, `:1647`). Adding a producer-side signal would require either (a) invoking `update_room_conditions` from a new listener (recursive design), or (b) hoisting `_compute_hvac_occupied` out of the tick loop and running it on every underlying edge (larger refactor, touches D1 producer, expands blast radius). The state-listener is the smallest addition that respects the operator scope ("shave the 5m tick ONLY").

**Why STATE_OCCUPIED and not `hvac_occupied`?** The `hvac_occupied` value differs from STATE_OCCUPIED only by (i) hallway exclusion (filtered at the listener) and (ii) the FALLING-edge tail-hold (`_effective_hvac_hold_seconds`). Rising edges of STATE_OCCUPIED and `hvac_occupied` coincide for non-hallway rooms — one edge, one trigger. Falling edges are handled by the tail-hold + vacancy grace + the next periodic tick, unchanged.

**Listener registration:** in `async_setup` after room coordinators are discovered (after the existing `update_room_conditions` seed at `hvac.py:1254` and before / adjacent to the periodic timer at `hvac.py:1355`). Entity list built by iterating `hass.config_entries.async_entries(DOMAIN)` for `ENTRY_TYPE_ROOM` (same pattern as `hvac_zones.py:561-583`), skipping hallway-typed entries and unloaded entries. Unsub appended to `self._unsub_listeners`.

**Re-registration on room lifecycle:** subscribe once to `SIGNAL_ROOM_ENTRY_LIFECYCLE` (`signals.py:199`) and rebuild the entity list on room add/remove/disable — REUSE the substrate-refresh pattern at `presence.py:2624-2651` / `:3333`. Unsub appended to `self._unsub_listeners`.

### 4.2 Rising-edge only — argued with numbers

Falling edges do NOT need a fast trigger:
- The retreat gate is `conditioning_retreat_ok = established AND fused-empty` (`hvac_zones.py:1085`). "Fused-empty" only becomes true after the last room's tail-hold expires + vacancy grace (10 min live) — a further ≤5 min tick delay is invisible against a ≥10 min gate.
- D6 stale-failsafe (~8 h) also cushions the falling side.
- Firing on falling edges would double trigger volume and risk falling-edge storms during multi-room vacancy sweeps.

Rising edges are the whole hot-entry-latency lever; they are what §9.5 measures.

### 4.3 Rate limiter (per-zone, cloud-call-rate protective)

**Constants (rung 1 — module const, `hvac_const.py`, "cloud API call-rate bound — change requires review"; sibling to `HVAC_DECISION_TICK`):**
- `HVAC_FAST_PATH_MIN_INTERVAL_S` — minimum seconds between accepted fast-path triggers per zone. Default sized from §3 (starting proposal 60; final value from measured p99).
- `HVAC_FAST_PATH_SLA_S = 10` — target trigger→cycle-complete latency (used only in tests + observability).

**State:** `self._fast_path_last_run_at: dict[str, datetime] = {}` — per zone_id, monotonic-safe (`dt_util.utcnow()`). No persistence; a restart legitimately reopens the limiter (the next periodic tick will run within 5 min anyway; a spurious burst-after-restart is bounded by the tick).

**Rule:** on rising edge for room R in zone Z, resolve Z; if `now - last[Z] < HVAC_FAST_PATH_MIN_INTERVAL_S`, deny (log `rate_limited`, NM LOW dedup'd per 5 min); else set `last[Z] = now` and dispatch. **Denials do NOT drop the observation** — the next periodic tick (≤5 min) is guaranteed to cover it. Restart backstop: the periodic timer at `hvac.py:1355-1360` is the discharge (suppression-needs-a-discharge rule).

**Whole-house vs per-zone cycle (operator-scope: leave as-is for now).** The existing `_run_decision_cycle` iterates every zone once. A trigger from zone Z runs a whole-house cycle. Cloud-call impact: each zone's preset write is gated by S1 lockout + delta checks (`hvac_preset.py:212-217`, `hvac_override.py:3187-3203`) — a cycle that doesn't change effective preset writes NOTHING to Carrier. So the cloud-bound impact of a fast-path cycle is bounded by "at most one preset write to zone Z" in the common case; sibling zones are quiescent. Keeping whole-house preserves cross-zone consistency (row-1/D5/D6/D7 interactions) with zero new invariants — this is the parsimonious choice. **See §6 for the per-zone-cycle question as a deliberate open item, NOT a blocker.**

### 4.4 Dwell-expiry follow-up (D2)

**Problem:** a fast-path trigger firing inside the 2-min lighting-session dwell (`hvac.py:2355-2368`) will hit `continue` and change nothing — the zone still waits for the next periodic tick (up to 5 min after dwell expires). Fast path only half-works without a follow-up. This is the D2 the operator flagged.

**Fix (minimal, per-zone dedup):**
- When the dwell branch is taken during a fast-path-originated cycle, compute `remaining_s = dwell_end - now`, and if no follow-up is pending for this zone, register `async_call_later(hass, remaining_s + FAST_PATH_DWELL_SLACK_S, _fast_path_dwell_followup)` and store `(unsub, dwell_end)` in `self._fast_path_pending_dwell: dict[str, tuple[unsub, datetime]]`. Append unsub to `self._unsub_listeners` (teardown-safe).
- The follow-up callback pops the entry and dispatches a normal fast-path trigger for zone Z. The rate limiter WILL grant it (the previous trigger set `last[Z]` at least dwell (=120 s) ago; if not, the follow-up is dropped — the periodic tick discharges).
- `FAST_PATH_DWELL_SLACK_S = 2` — rung-1 module const, "give the lighting session clock a beat past its dwell edge."

**Dedup:** if another fast-path trigger for the same zone lands while a follow-up is pending, do nothing (the pending timer will fire; the extra trigger's rate-limit denial is the natural coalesce).

### 4.5 Interaction with existing triggers + coexistence

- **Boot-settle (`hvac.py:1510-1552`):** `_async_decision_cycle` early-returns while `_boot_settle_done` is False. The fast path calls `_async_decision_cycle` (NOT `_run_decision_cycle` directly), so boot-settle suppression is respected — the release kickoff at :1544 remains the sole discharge. NEW listener registration must survive `async_teardown` unchanged.
- **House-state change (`hvac.py:3131`):** untouched; runs its own trigger under the same lock.
- **Pre-arrival (`hvac.py:4002`):** untouched. A fast-path trigger for a zone already in `_pre_arrival_zones` is not suppressed at the trigger — the dwell block at `:2365` already exempts pre-arrival zones from dwell, and the cycle body handles the state.
- **Cycle lock (`hvac.py:1592-1598`):** re-entrancy guarded — a trigger landing during a running cycle is skipped with `debug` log. Correct: the running cycle already reads current occupancy (`update_room_conditions` at :1647). No task explosion.
- **Egress initial-restore gate:** unaffected (egress force-release at :1406 remains the discharge).
- **`SIGNAL_ZM_ZONES_UPDATED` (`hvac.py:1211`):** unrelated (zone add/delete flow); no conflict.

### 4.6 Producer refresh

The fast-path trigger dispatches `self._async_decision_cycle()` → `_run_decision_cycle` → `update_room_conditions` at `hvac.py:1647`. The producer runs unchanged; no separate producer refresh site to maintain. This preserves §3.1 semantics (hallway exclusion, tail-hold, night/day table selection).

---

## 5. Deliverables

### D0 — Empirical rate probe (READ-ONLY, gate)
See §3. Report → `docs/planning/AUDIT_hvac_fast_path_rate_2026_09_26.md`. Blocks D2.

**Acceptance:**
- **Verify:** table of per-zone rising-edge rates (median / p95 / max / bursts-per-5-min p95) over the last 30 days.
- **Verify:** proposed `HVAC_FAST_PATH_MIN_INTERVAL_S` value + one-line justification citing the p99 inter-edge gap.
- **Live:** N/A (offline probe).

### D1 — Rate limiter primitive + observability
Add `HVAC_FAST_PATH_MIN_INTERVAL_S`, `HVAC_FAST_PATH_SLA_S`, `FAST_PATH_DWELL_SLACK_S` to `hvac_const.py` (rung 1, sibling comment to `HVAC_DECISION_TICK`). Add `self._fast_path_last_run_at`, `self._fast_path_pending_dwell` to `HVACCoordinator.__init__`. Add a `fast_path_reason` attribute to the decision-cycle log row (`coordinator_diagnostics.DecisionLogger`) — enum: `periodic | boot_settle_kick | house_state | pre_arrival | fast_path | fast_path_dwell_followup | rate_limited | skipped_reentrant`.

**Acceptance:**
- **Test:** `test_fast_path_rate_limiter_denies_within_interval` (unit; drills the limiter dict).
- **Test:** `test_fast_path_rate_limiter_grants_after_interval` (freeze clock helper, no wall-clock).
- **Sensor:** `sensor.ura_hvac_coordinator_decision_cycle` gains attr `fast_path_reason` on latest row.
- **Live:** post-restart, at least one decision-cycle row within 24 h with `fast_path_reason == "fast_path"`; no row with `fast_path_reason == "skipped_reentrant"` under normal steady-state.

### D2 — Fast-path trigger wiring (rising edge, hallway-excluded)
Register `async_track_state_change_event` for the filtered set in `async_setup`. Handler resolves room → zone via the same iteration as `binary_sensor.py:908-910`, checks CONF_ROOM_TYPE, filters rising edge (old ∈ {off, unknown, unavailable, None} AND new == "on"), consults limiter, dispatches `_async_decision_cycle` via `hass.async_create_task` tracked in `self._pending_tasks` (identical to `hvac.py:3131-3133`). Subscribe to `SIGNAL_ROOM_ENTRY_LIFECYCLE` to rebuild the entity list on room add/remove.

**Wire-in anchors (mandatory per `feedback_wire_in_anchor_mandatory.md`):**
- `test_fast_path_registered_at_setup` — asserts `async_track_state_change_event` is called with the expected non-hallway entity list at `async_setup` exit; **call-neuter drill** (comment out the registration line → this test FAILS RED; restore → GREEN).
- `test_fast_path_rebuilds_on_lifecycle_signal` — dispatches `SIGNAL_ROOM_ENTRY_LIFECYCLE` with a new room and asserts the entity set expanded; neuter drill on the re-subscribe.
- `test_fast_path_hallway_excluded_end_to_end` — a state change on a hallway room's occupied sensor does NOT dispatch a cycle (behavioural anchor, not source grep).
- `test_fast_path_falling_edge_ignored` — off→on triggers; on→off does not.
- `test_fast_path_dispatches_decision_cycle_via_async_create_task` — spy on `_async_decision_cycle`; assert task added to `_pending_tasks`.

**Acceptance:**
- **Verify:** a synthetic rising edge on a non-hallway room's occupancy sensor produces exactly one `_async_decision_cycle` call within `FAST_PATH_SLA_S` in tests.
- **Verify:** hallway room edges produce zero calls.
- **Test:** the five wire-in tests above, all with mutation drills.
- **Live:** recorder query — for at least 3 hot-entry events in the first 24 h post-restart, the gap between `binary_sensor.<room>_<room>_occupied` rising edge and the next preset change on that zone's climate entity is ≤ (existing entry dwell 120 s + `FAST_PATH_SLA_S`) = **≤ ~130 s**, vs the current ≤ ~420 s. Recorder-measurable; the discriminating number is the p50 hot-entry latency BEFORE vs AFTER.

### D3 — Dwell-expiry follow-up
Implement the D2-flagged behaviour from §4.4. Per-zone dedup; unsub on `_unsub_listeners`.

**Wire-in anchors:**
- `test_dwell_active_schedules_followup` — fast-path trigger inside dwell window schedules exactly one follow-up; neuter drill on the `async_call_later` call.
- `test_dwell_followup_dispatches_second_cycle` — advance clock past dwell + slack; assert follow-up fires and dispatches a cycle.
- `test_dwell_followup_deduplicated` — two triggers inside dwell schedule ONE follow-up, not two.
- `test_dwell_followup_cancelled_on_teardown` — call `async_unload` mid-window; assert no callback fires afterwards (teardown-safety; Bug Class #50).

**Acceptance:**
- **Verify:** an entry that lands inside the 2-min dwell produces a second decision cycle within (dwell_remaining + FAST_PATH_DWELL_SLACK_S + FAST_PATH_SLA_S).
- **Sensor:** the decision-cycle log row for the second cycle has `fast_path_reason == "fast_path_dwell_followup"`.
- **Live:** recorder — for a hot entry that begins mid-dwell (rare but real), the preset change on the zone lands within ~132 s of dwell expiry (vs waiting for the next tick up to ~5 min).

### D4 — Teardown + reload-storm safety
- All new unsubs on `self._unsub_listeners` (drained by `_cancel_listeners` in `async_teardown`).
- On `SIGNAL_ROOM_ENTRY_LIFECYCLE` (loaded/unloaded), the entity list rebuilder is IDEMPOTENT: drops the previous state-change unsub before registering a new one (avoid duplicate dispatch during a reload storm — see `project_reload_storm_refuted_restart_storm_live.md`).
- Fast-path trigger during boot-settle is a no-op by construction (`_async_decision_cycle` early-returns); confirm with a test.

**Acceptance:**
- **Test:** `test_reload_storm_no_duplicate_dispatch` — fire `SIGNAL_ROOM_ENTRY_LIFECYCLE` 5 times in ≤ 1 s; assert only one active listener set exists (spy on `async_track_state_change_event` unsub count).
- **Test:** `test_fast_path_no_op_during_boot_settle` — trigger while `_boot_settle_done=False`; assert no cycle runs and `_boot_settle_hvac_suppressed` increments.
- **Live:** post-restart, no `RuntimeError` in HA logs referencing fast-path; `hvac_fast_path_rate_limited` NM count in first hour is ≤ once per zone (any more = storm; blocker).

---

## 6. Open operator question (only where truly needed)

**Q1 — Per-zone vs whole-house cycle.** The operator scope leaves the decision cycle whole-house. §4.3 argues this is safe because sibling zones write nothing when their effective preset is unchanged. **Ask only if D0 shows daily fast-path trigger volume + cross-zone S1 write rate would push the Carrier per-thermostat write cadence into a new regime** (D0 will surface this). Otherwise: default to whole-house, no operator ask.

No other open questions — dwell-expiry, rising-edge-only, rate-limiter placement, and non-goals are pre-decided above.

---

## 7. Non-goals (explicit)

- No change to entry dwell (stays 2 min; operator-set 2026-09-26).
- No change to tail-hold, vacancy grace, night tail-hold, hallway exclusion, retreat semantics, D5/D6/D7/D8/D9, override switch semantics (§9c decision LEAVE AS IS).
- No falling-edge fast path (argued §4.2).
- No new preset/setpoint write sites; the trigger runs the EXISTING cycle earlier — nothing else changes downstream.
- No per-zone decision cycle refactor (deferred; see §6 Q1).
- No producer refactor (no hoisting `_compute_hvac_occupied` out of the tick).
- No knob exposed to operator UI — limiter is rung-1 module const, cloud-bound.
- No Nest/other-brand behaviour changes (W1-B territory).

---

## 8. Tier classification

**Tier 2-DB (three framing-disjoint reviews + live validation + README write-back).**

**Rationale:** shared decision cycle is a cross-coordinator primitive (row-1 preset, D5 shed, D6 failsafe, D7 night trust, D9, F4 arrester comfort-delay all run inside it). A trigger-rate defect could induce a cloud-call storm (§7 lockout mechanics, §9.1 self-lockout hazard). Regression-prone per standing policy (`feedback_tier2db_for_regression_prone.md`).

**Reviewer framings (framing-disjoint, per Tier 2-DB doctrine — the "DB" is historical, the three-framing rule stands):**

- **A — Local correctness + limiter arithmetic.** Rising-edge classification correct across HA state transitions (off/on/unknown/unavailable/None); dedup dict math; per-zone key resolution; hallway exclusion path; SLA measurement.
- **B — Integration / decision-cycle integrity + Carrier cloud bound.** Every existing trigger path unchanged; re-entrancy guard holds under storm; whole-house cycle preserves cross-zone precedence; Carrier write rate post-fast-path stays inside the 5-min-derived envelope; boot-settle + egress-gate + reload-storm interactions clean.
- **C — Test authority via real per-site mutation.** Neuter the state-change registration, the rate-limiter check, the dwell-followup scheduler, and the lifecycle re-subscribe individually; each mutation MUST turn a SPECIFIC test RED (no aggregate monkeypatch). Confirm no fast-path test passes on stale `.pyc` (`feedback_mutation_verification_pycache_staleness.md`).

**Adversarial completeness (Reviewer D role, elevated if the invariant risks pull it up):** re-enumerate every downstream site the whole-house cycle touches when triggered by a single zone edge, and produce a legal-config reachable case where INV falsifies (e.g., dwell + rate-limit + reload-storm collision).

**Plan review (mandatory per CLAUDE.md "Plan Review — TIERED"):** ONE adversarial plan review before build dispatch — re-run the §1.1 prior-art greps, re-derive the trigger enumeration in §4.1, verify the falsifiable invariant in §2 is actually falsifiable.

---

## 9. Sequencing + overlap flag (v5.103.15)

**Do NOT dispatch build until `feature/hvac-live-room-establishment` merges to `develop`.** Overlapping regions in `hvac.py`:

- Subscribe block `:1131-1213` — v5.103.15 may add establishment-related subscribes; the new state-change subscribe (D2) must be added AFTER those, without re-ordering.
- `_run_decision_cycle` `:1600-1700` — v5.103.15 round-3 fix touches `_row1_hold_write` scoping (`:2002 / :2056 / :2533`); D3's follow-up scheduler must not collide with hold-write bookkeeping.
- `update_room_conditions` at `:1647` — unchanged in v5.103.15 (verify at dispatch).
- The v5.103.15 "live-room" gate applies to `is_zone_hvac_established` — the fast path's zone resolution reads the same room→zone map but does NOT read establishment (rising edges bypass establishment; the retreat gate is untouched by this plan).

**At build dispatch:** re-verify §1.1 REUSE citations against the merged `develop` (line numbers may shift). This is a plan-review checklist item, not a re-plan.

---

## 10. Knobs on the ladder (per `feedback_numbers_get_knobs`)

| Number | Rung | Why |
|---|---|---|
| `HVAC_FAST_PATH_MIN_INTERVAL_S` | **1 — module const** (`hvac_const.py`, sibling to `HVAC_DECISION_TICK`) | Cloud-API call-rate protective bound; tuning requires the same review posture as the periodic tick. Not an operator knob. |
| `HVAC_FAST_PATH_SLA_S` | **1 — module const** | Test/observability target only, not behavioural. |
| `FAST_PATH_DWELL_SLACK_S` | **1 — module const** | Correctness slack past the lighting-session clock edge; changing it changes wall-clock coupling risk. Not operator-facing. |

**Kill-switch:** none. The fast path degrades to the current behaviour (5-min tick) if the state-change subscription fails to register — a warning log + one NM LOW at boot; no code path leaves the periodic timer unregistered. The rate-limiter can be effectively disabled by setting the interval higher than any real edge rate, but that is not an operator-exposed knob.

---

## 11. Producer / Consumer map (post-fix, per operator-2026-08-16 rule)

**PRODUCER of the new "fast-path trigger" value:** HA state-change events for the filtered room-occupied entity set. Dependency health: each source is `binary_sensor.<room>_<room>_occupied` from the URA room coordinator (`coordinator.py` STATE_OCCUPIED writes). External ground truth: motion/mmWave/BLE substrate. If a source sensor goes `unavailable`, its rising edges vanish — the periodic tick still discharges within 5 min.

**CONSUMER + call-sites:**
- `HVACCoordinator._async_decision_cycle` (`hvac.py:1564`) — sole consumer, invoked via `async_create_task` → task tracked in `_pending_tasks`. Trust-decision (runs the whole retreat/preset pipeline), not display.
- Decision-log row (`fast_path_reason` field, D1) — display + audit only.
- Rate-limiter NM notice — display + audit only.

**No new trust downstream** — this plan changes WHEN the cycle runs, not WHAT it decides.

---

## 12. Plan Completion Tracking (template for post-build)

At build close, the plan-completion table lists D0/D1/D2/D3/D4 with status (shipped / deferred / dropped) and, for deferrals, WHERE it is carded (default: as children of `HVAC-W2-OCCUPANCY-TRUTH`).

---

## Appendix A — Falsifiable INV restated for reviewer D

> **Under normal steady-state operation (boot-settle released, no active reload storm), for every HVAC-occupancy rising edge on a live non-hallway room R in zone Z, a `_run_decision_cycle` completes within `HVAC_FAST_PATH_SLA_S` seconds of the source `state_changed` event unless the per-zone rate-limiter denied the trigger; AND no per-zone triggered-cycle rate exceeds `1 / HVAC_FAST_PATH_MIN_INTERVAL_S`; AND every fast-path subscription, timer, and pending follow-up is cancelled inside `async_teardown` (no orphan callbacks, no writes after unload). A legal-config, recorder-reachable violation of ANY conjunct falsifies INV.**
