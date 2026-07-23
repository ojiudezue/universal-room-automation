# PLANNING — EC Blind-Window EVSE Guard + DP Decision Persistence + Outage-Frequency Probe

**Cycle trigger:** 2026-07-20 evening incident (Envoy local API outage
20:04–21:44 CDT). During the ~100-min blind window, off-peak ensure-on
started Garage A EVSE at 21:00:16 (Emporia recorder: ~5,045 W, status
Charging). The EV-battery-drain guard's intent (drain_target_soc=80,
`energy_ev_battery_drain_soc`) could not be enforced because Envoy
reserve writes had no verifiable oracle ("no commands issued" per EC
tick log 20:23–21:43). Battery (inverter-local self_consumption) fed a
~5 kW car + 10–18 kW house from ~72 % down to 13 % until the operator
manually stopped the EVSE at 21:43:37. Envoy polls resumed at
21:44:46 (69 s after EVSE stop; load-correlation N=1, unproven).
BAEC/DP plan cycled `hold_pre_eval` ↔ `hold_only` every 5 min through
the window and never transitioned; forensics dead-ended because
in-window eval reasons are not persisted (only latest snapshot
survives). The v5.17.x SOC-divergence detector fired correctly at
21:45 (envoy=13 vs stale cloud=72.6) — but only post-recovery.

**Invariant violated (EC manual §2.4b audit conclusion):** "no path
drains the home battery into a car outside BAEC's deliberate
transition window." Path 11 (off-peak ensure-on) violated it because
its precedence chain assumes battery-protection peers are able to
observe SOC and verify writes — neither was true during the outage.

**External root cause (out of scope):** the Envoy blip cause is
device-side and unproven. This cycle hardens URA's posture *under*
Envoy outages; it does not attempt to fix or predict them.

---

## Institutional context verified

**Greps run + results:**

- Off-peak ensure-on precedence chain — REUSED at
  `domain_coordinators/energy_pool.py:569-690` (`tou_period ==
  "off_peak"` branch inside `determine_actions`). Existing carry-over
  guards: `_stronger_peer_holds` (603), `_paused_by_dp` (608),
  `grid_charge_on` breaker-safety (627), `force_charge_active` escape
  (654). D1 will add ONE additional pre-check adjacent to these,
  BEFORE line 662's `if not state["is_on"]` — REUSED shape.
- Blind-hold posture — REUSED at
  `domain_coordinators/energy.py:4316-4426` ("Envoy unavailable
  (SOC=%s…) — holding current state" / "no commands issued"), and the
  `is_blind_hold` flag already threaded into strategy snapshots at
  `energy.py:3406` and `energy.py:3576` (formula
  `(not _env_ok) and _bat_soc is None`). D1 consumes this existing
  signal — NEW public accessor on `EnergyCoordinator` proposed
  (`blind_hold_active` property) because current sites are private
  locals; justified because `energy_pool.py` must not reach into
  private state.
- Write-verify machinery — REUSED at
  `domain_coordinators/energy_write_verify.py` (STATUS_* constants,
  pending-attempt watchdog, `WRITE_VERIFY_SURFACE_RESERVE` at :41).
  D1 will introduce a coarse "reserve write path is unverifiable
  right now" predicate derived from the existing surface record's
  status (STATUS_NO_DATA / STATUS_INCONCLUSIVE / pending beyond
  `CONF_PENDING_ATTEMPT_3_AGE_S`) — REUSED status vocabulary; the
  predicate itself is NEW (`reserve_write_verifiable()`), justified
  because no coordinator currently exposes a single "can we prove a
  reserve command took" boolean.
- Force-charge escape (row 2 of §2.4b) — REUSED at
  `energy_pool.py:654` (`force_charge_active`). D1 preserves this by
  ordering the new blind-window pre-check AFTER the existing
  `force_charge_active` short-circuit — no life-safety regression.
- `decision_log` DAO — REUSED at `database.py:640-679` (schema
  established c0.4; columns: `id, timestamp, coordinator_id,
  decision_type, scope, situation_classified, urgency, confidence,
  context_json, action_json, expected_savings_kwh,
  expected_cost_savings, expected_comfort_impact,
  constraints_published, devices_commanded`). Existing writer at
  `database.py:2063-2069` (INSERT template). D2 will REUSE this DAO
  with `decision_type='dp_eval'`, `scope='house'`,
  `coordinator_id='energy'`; inputs go in `context_json`. NEW dedicated
  table is NOT proposed — the shape fits cleanly.
- BAEC / DP state machine — REUSED at `energy.py`,
  `energy_drain_precedence.py`, `energy_pool.py`. Existing hooks:
  `_evaluate_dp_plan` cadence is the tick already producing
  `hold_pre_eval` / `hold_only` snapshots — D2 hooks the persistence
  call at that site (no new tick, no new scheduler).
- §2.4b precedence table — READ in
  `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` (post-2026-07-20
  reconciliation of record, per commit a0d48a95). D1's new row inserts
  BETWEEN existing row 2 (force-charge, life-safety) and existing row
  11 (off-peak ensure-on): "row 2.5 — blind-window defer".

**Prior planning docs consulted (filename + relevance):**

- `docs/planning/PLANNING_ev_charge_start_deadband.md` — sibling case
  (drain-pause release read stale reserve during blind window);
  informs D1's shape (thread live blindness, don't cache).
- `docs/planning/PLANNING_evse_drain_precedence.md` — §2.4b precedence
  authoring; row-numbering + must-start-by liveness patterns.
- `docs/planning/AUDIT_envoy_telemetry_pairing_manual.md` — precedent
  for the D3 Measure-Before-Build probe artifact (hand-built fixture).
- `docs/planning/PLANNING_nm_cycle_c_routing_matrix.md` — skim only
  (no bearing).
- `docs/readmes/README_v5.15.0.md`, `README_v5.24.0.md` — recent EC
  ship shape and validation-table format.

**Memory bodies pulled:**

- `project_ev_charge_start_deadband.md` — the "static-vs-live floor"
  bug family; D1 avoids re-introducing it.
- `project_inclement_arbitrage_wait_floor_gap.md` — Bug Class #53
  (computed-but-not-consumed); D1's completeness pass must enumerate
  all ensure-on sites, not just row 11.
- `project_v5_5_0_inclement_weather_shipped.md` — precedent for adding
  a defer posture on top of an existing precedence chain.
- `project_optimizer_db_write_flood_incident_2026_06_09.md` — D2's
  write-volume budget is derived FROM this incident's lesson (one row
  per eval tick max, ~12/hr, batched with existing write-queue).

**Design docs read:**

- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.4b, §2.5
  (blind-hold contract), §2.6 (write-verify).

**Code locations surveyed end-to-end during scoping:**

- `domain_coordinators/energy_pool.py` — `determine_actions`
  (off-peak branch full read).
- `domain_coordinators/energy_write_verify.py` — status vocabulary +
  watchdog window (first 200 lines).
- `domain_coordinators/energy.py` :4300-4430 (blind-hold return
  branch), :3400-3580 (`is_blind_hold` populator sites).
- `database.py` :637-700 (decision_log DDL), :2060-2075 (writer).

---

## Falsifiable invariant (Tier 3 — state up front, D-pass job is to break it)

> **INV-BW1 (Blind-Window Battery Isolation):** while SOC is
> unresolved (`is_blind_hold == True`) AND the most recent reserve
> write cannot be verified via the v5.17.5 write-verify oracle
> (`reserve_write_verifiable() == False`), **no EVSE transitions
> OFF→ON via any ensure-on precedence row**, and any ensure-on that
> WOULD have fired is logged (both to `_LOGGER.info` and to
> `decision_log` with `decision_type='blind_window_defer'`).
>
> **Escape hatch (explicit, single):** row 2 force-charge
> (`force_charge_active == True`) remains authoritative and preempts
> INV-BW1. No other row does.
>
> **Fail-safe leg (D1-b):** an EVSE ALREADY ON when INV-BW1 first
> engages this tick is transitioned OFF (paused) and claimed under a
> new pause-owner `_paused_by_blind_window`; carry-over on subsequent
> ticks holds it OFF until the blind window clears. Rationale: the
> incident's actual failure was an ensure-on that fired 56 min INTO
> the outage — a purely-defer posture would still have allowed a
> pre-outage-started charge to drain the battery.

Adversarial-completeness pass (Tier-3 D) must enumerate every
ensure-on site, not just row 11, and confirm each routes through the
new guard OR is provably out of scope (e.g. excess-solar path — solar
production during a local-Envoy blackout is itself observable how?
D-pass must resolve).

---

## D1 — Blind-Window EVSE Guard

**What:** insert a new precedence pre-check ("row 2.5") in
`energy_pool.determine_actions` off-peak branch (and any peer
ensure-on site the D-pass surfaces) that DEFERS turn-on and PAUSES an
already-on EVSE while `blind_hold_active AND NOT reserve_write_verifiable()`.
Preserves row 2 force-charge escape. Emits one `_LOGGER.info` per
defer + one `decision_log` row per defer (dedup key: `evse_id +
blind-window-epoch` — a single epoch spans the whole outage; not one
row per tick per EVSE).

**Files touched:**

- `domain_coordinators/energy_pool.py` — new pre-check + new
  `_paused_by_blind_window` set + carry-over integration into
  `_stronger_peer_holds` and `_paused_by_dp`-adjacent sites; classify
  reason string for `_classify_evse`.
- `domain_coordinators/energy.py` — NEW public property
  `blind_hold_active` (returns the existing local computation);
  NEW public method `reserve_write_verifiable() -> bool` delegating
  to `energy_write_verify` state.
- `domain_coordinators/energy_write_verify.py` — NEW helper
  `is_reserve_verifiable()` reading current surface record's status
  and pending age.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` — §2.4b row 2.5
  added; §2.5 blind-hold contract extended with the EVSE clause.

**Numbers get knobs:**

- `CONF_BLIND_WINDOW_MAX_DEFER_MIN` (module constant,
  `energy_const.py`) — **rung 1 (module constant)**. Default: gated
  by D3 probe. If the probe shows outages routinely > 60 min AND
  must-start-by would be violated, this constant caps the defer and
  hands the decision to must-start-by. Rationale for rung 1: this is
  a safety-vs-liveness tradeoff; operator should not tune this from
  a dashboard slider without review. Kill-switch semantics: value
  `0` disables the defer (D1 becomes a no-op — emergency backout
  without a code push, via a code-change hotfix).

**Acceptance criteria:**

- **Verify (unit):** with `blind_hold_active=True,
  reserve_write_verifiable=False`, off-peak tick with EVSE OFF
  produces NO turn_on action and one `decision_log` row.
- **Verify (unit):** same conditions with EVSE ON produces exactly
  one `turn_off` action, adds to `_paused_by_blind_window`, and
  subsequent ticks are idempotent (no re-turn_off spam).
- **Verify (unit):** with `force_charge_active=True` AND blind-window
  true, EVSE turns ON (row 2 escape preserved).
- **Verify (Tier-3 D — source mutation):** editing out ONE ensure-on
  site's new guard-call causes a specific test to fail; restore, run
  green.
- **Sensor:** `sensor.ura_energy_coordinator_battery_strategy` gains
  attribute `blind_window_defers_this_epoch` (integer count) —
  observable during real outage.
- **Test:** `test_blind_window_defers_ensure_on`,
  `test_blind_window_pauses_already_on_evse`,
  `test_blind_window_preserves_force_charge`,
  `test_blind_window_carry_over_idempotent`,
  `test_blind_window_clears_on_envoy_recovery`.
- **Live:** on next real Envoy blip (any duration ≥ 10 min OR
  operator-injected via disabling the Envoy integration in HA UI),
  EC log shows "blind-window defer" line, `decision_log` shows a
  `blind_window_defer` row, and Emporia recorder shows EVSE power
  ≤ 100 W throughout. If an EVSE was already charging at blind-window
  entry, Emporia shows a single OFF transition within one 5-min tick.

---

## D2 — DP Eval Decision Persistence

**What:** at each DP plan eval tick (site of the observed
`hold_pre_eval` ↔ `hold_only` snapshot cycling), write ONE row to
`decision_log` with `decision_type='dp_eval'`,
`coordinator_id='energy'`, `scope='house'`,
`context_json = {state, prior_state, decision, reason, charger_rate_kw,
soc, is_blind_hold, reserve_verifiable, target_soc,
drain_target_soc, tou_period, force_charge_active}`,
`action_json = {transitioned: bool, next_state}`. REUSES existing
DAO — no schema change. Writes are batched into the existing
`database.py` write queue (which the v5.2.x incident forced us to
build), so no separate throttle needed beyond one-row-per-tick.

**Write-volume budget:** DP eval cadence is 5 min → 12 rows/hr →
~288 rows/day. Compared to the v5.2.x flood (per-cycle multi-row
per-finding), this is ~2 orders of magnitude below the fault
threshold. Retention: rely on existing `decision_log` retention
policy (verify one exists during build; if not, D2 adds a 90-day
prune to the daily maintenance job — REUSED shape).

**Files touched:**

- `domain_coordinators/energy.py` — call `database.log_decision(...)`
  from the DP eval site after each snapshot is computed.
- `database.py` — no schema change; verify/confirm existing
  `log_decision(...)` writer signature covers all fields (it does per
  :2063-2075). If retention not present, add prune query.

**Numbers get knobs:**

- `CONF_DP_EVAL_LOG_RETENTION_DAYS` (module constant,
  `energy_const.py`) — **rung 1**. Default 90 days. Rung-1 because
  retention change should be a code review (regulatory /
  forensic-scope decision, not a dashboard turn).

**Acceptance criteria:**

- **Verify (unit):** one DP eval → exactly one `decision_log` row
  with all listed context fields non-null (except SOC when
  `is_blind_hold=True`).
- **Sensor:** none required (DB-only observation surface is
  intentional — DP eval spam should not populate an attribute).
- **Test:** `test_dp_eval_persists_one_row_per_tick`,
  `test_dp_eval_context_shape_complete`,
  `test_dp_eval_row_survives_restart`.
- **Live:** during any DP eval tick post-deploy, `sqlite3` query
  `SELECT COUNT(*), MAX(timestamp) FROM decision_log WHERE
  decision_type='dp_eval'` shows count increasing at ~12/hr and
  `context_json` inspection shows the full field set. During the
  next Envoy blip (or D3-injected outage), rows accumulate with
  `is_blind_hold=true` and `reserve_verifiable=false` — the exact
  forensic trace the 2026-07-20 incident lacked.

---

## D3 — Measure-Before-Build Probe: Envoy Outage Frequency

**What:** one-shot read-only recorder probe extracting unavailable
windows for 2–3 Envoy entities (candidates:
`sensor.envoy_482543015950_battery`,
`sensor.envoy_482543015950_current_power_production`, plus one
Enpower reserve-facing entity) across the FULL recorder retention.
Report: histogram of outage durations, count of outages, longest
outage, distribution of inter-outage gaps. Run via `ssh ha "python3 -"
< scripts/probe_envoy_outages.py`. Artifact:
`docs/planning/PROBE_envoy_outage_frequency.md`.

**Gate on D1 final shape:**

- **If outages are RARE and SHORT** (< 1/month, all < 30 min): D1
  ships without `CONF_BLIND_WINDOW_MAX_DEFER_MIN` machinery — the
  simple defer is sufficient; must-start-by is untouched.
- **If outages are COMMON or LONG** (any > 60 min, or > 1/week):
  D1 MUST integrate with the existing DP must-start-by machinery
  (`_arm_dp_must_start_by_timer` at `energy.py:4337`) so cars still
  charge overnight. `CONF_BLIND_WINDOW_MAX_DEFER_MIN` becomes
  load-bearing; its default is set from the probe.
- **If outages cluster around specific times** (e.g. Envoy firmware
  push): report to operator; no D1 change but informs D3-follow-on
  investigation.

**Files created:**

- `scripts/probe_envoy_outages.py` — read-only recorder query.
- `docs/planning/PROBE_envoy_outage_frequency.md` — results table +
  D1-shape verdict.

**Acceptance criteria:**

- **Verify:** probe report committed BEFORE D1 build starts.
- **Live:** N/A (offline probe).

---

## Tier classification

**Recommendation: Tier 3 (four framing-disjoint reviews + operator
checkpoint).**

Honest argument:

- **Trust-hierarchy ripple:** D1 threads a new predicate across
  `energy` → `energy_write_verify` → `energy_pool` → `§2.4b` precedence
  table → BAEC/DP interaction. This is precisely the ripple shape the
  standing policy calls out.
- **Cost-AND-safety:** the failure mode is silent money loss
  (draining a $10k battery into an EV at ~5 kW during pre-peak
  hours) AND comfort/safety loss (house on 13 % battery for HVAC
  overnight is one grid-outage away from a cold night). This is the
  Tier 3 "cost-AND-safety" trigger explicitly.
- **State-machine × time seam:** blind-window is a time-bounded state
  the operator cannot easily reproduce; the recent history of bugs
  at this seam (rung-gate seam, wall-clock-coupled tests, drain-pause
  static-floor) argues for the Tier-3 D-pass framing (adversarial
  completeness, per-site source mutation).
- **Bug Class #53 risk (computed-but-not-consumed):** the D-pass
  must enumerate EVERY ensure-on site, not just row 11 — that is
  exactly the Tier-3 D framing.

Tier-2-DB (three reviews) is not sufficient because the load-bearing
invariant INV-BW1 is a "no path" claim across a precedence chain with
seven+ rows; only the Tier-3 D-pass explicitly re-enumerates
pre-existing code and requires a legal-config reachable repro per
flagged leak.

Operator checkpoint BEFORE deploy is MANDATORY per Tier 3 protocol
(the money+safety blast radius warrants it even though the observed
incident already happened).

---

## Deliverable summary (return to caller)

1. **D3 first** (Measure-Before-Build): probe committed as
   `docs/planning/PROBE_envoy_outage_frequency.md`; gates D1's final
   shape (with vs without `CONF_BLIND_WINDOW_MAX_DEFER_MIN` +
   must-start-by integration).
2. **D1**: new "row 2.5" blind-window guard in
   `energy_pool.determine_actions` + fail-safe pause of already-on
   EVSEs + `_paused_by_blind_window` carry-over + §2.4b + §2.5 doc
   updates. Preserves row 2 force-charge. Consumes REUSED
   `is_blind_hold` (energy.py:3406/3576) and NEW predicate
   `reserve_write_verifiable()` (thin wrapper over existing
   write-verify status vocabulary).
3. **D2**: persist each DP eval via REUSED `decision_log` DAO
   (database.py:640-679) with `decision_type='dp_eval'`; ~12
   rows/hr; no schema change.

---

## Open questions (need operator input before build)

1. **Excess-solar path during a local-Envoy outage:** is solar
   production observable via a non-Envoy path (Emporia panel-level?
   Enphase cloud when local API is down?)? If NOT, does the
   excess-solar ensure-on branch also need INV-BW1? (D-pass will
   force the answer; better to pre-answer.)
2. **Fail-safe pause vs defer-only:** D1-b (paus­ing an already-on
   EVSE when blind-window engages mid-charge) is the operator-
   consequential change — a car mid-charge gets interrupted. The
   incident argues for it; is there a scenario (e.g. must-leave-by
   morning) where the operator would rather bleed the battery than
   interrupt? Suggestion: gate D1-b on `drain_target_soc` vs current
   battery SOC — if battery is already below drain_target, pause; if
   above, defer-only. Needs operator ratify.
3. **"Reserve write unverifiable" latency:** the write-verify
   watchdog window (`CONF_PENDING_ATTEMPT_3_AGE_S`) defines how long
   before we call a pending write "unverifiable". Is the current
   default aggressive enough to catch a fresh outage's first tick,
   or does D1 need its own faster predicate (e.g. "envoy entity
   unavailable for > 1 tick")?
4. **Retention for `dp_eval` rows:** 90-day default proposed;
   operator preference? Forensic-window operator has invoked in
   past incidents = 7-14 days, so 90 is comfortably above.
5. **D3 probe scope:** should it also correlate Envoy outages with
   HA restart events / integration reload events, so the "spontaneous
   recovery" hypothesis (load-driven?) has more data? Cheap to add.

---

## Operator adjudication — 2026-07-21 late (verified against code/registry)

**Q1 (fail-safe semantics) — operator correction accepted.** The drain
guard's actual code semantics (energy_pool.py:1184): pause fires when
battery is DISCHARGING and SOC < threshold (80). At/below the threshold,
car charging is legitimate only when grid covers it (battery held); above
it, battery contribution is tolerated (surplus zone). So the blind-window
fail-safe decision is NOT "below target → pause"; it is: pause mid-charge
UNLESS the guard can establish EITHER (a) battery-not-discharging from a
live non-Envoy source, or (b) SOC ≥ threshold via the LKG envelope (Q4).

**Q2 (excess-solar backup path) — CONFIRMED, Emporia mains has the
semantics.** Registry: `sensor.mains_vue_2_mainstogrid_*` (export),
`sensor.mains_vue_3_mainsfromgrid_*` (import),
`sensor.mainw_vue_balance_*` (net) + `_power_minute_average` variants.
Export power > threshold = Envoy-independent excess-solar signal. New
deliverable D4: optional CONF for a backup net/export sensor (config
path, default unset = current behavior); excess-solar claim may consult
it when Envoy is blind. Guard covers excess-solar path per operator "yes".

**Q3 — dissolved, operator right.** EC already computes `envoy_available`
per tick (battery-strategy attr) — the fast local predicate exists. Use
BOTH: envoy_available (fast entry) + write-verify staleness (confirm for
the write leg). No new detection surface.
**New finding from this check:** the CLOUD fallback entity
(`sensor.iq_battery_hacs_battery_overall_charge`) went unavailable at the
SAME instants as the local entities (20:09:13, 20:20:34) and recovered
the same minute (21:44) — identical timestamps across independent
integrations point to a shared cause (likely a host/LAN network event,
unproven). Design consequence: the guard MUST NOT assume the cloud tier
survives local outages — last night it did not.

**Q4 (operator proposal: persist last local SOC) — adopted as D5.**
The 3-tier resolver already holds an in-RAM LKG (energy_battery.py:290,
max age DEFAULT_SOC_LKG_MAX_AGE_S=300s) and cloud fallback (600s cap).
Last night ALL tiers expired/died: 84-min outage >> 300s LKG, cloud
entity down with it → SOC=None for the whole window. D5:
(a) persist LKG (value + timestamp) across restart via the existing EC
persistence shape; (b) extend LKG beyond 300s as a DECAY ENVELOPE, not a
point estimate: [lkg − max_discharge_kw×Δt/capacity, lkg +
max_charge_kw×Δt/capacity]. The blind-window guard consumes the envelope:
lower bound ≥ drain threshold → mid-charge EVSE may ride; else pause.
Envelope parameters are physics constants (rung 1). This turns "blind"
from binary into bounded-uncertainty, and directly answers Q1's fail-safe.

Retention (Q4-minor): dp_eval log 90 days ratified by default. Q5 probe
refinement: skipped (cause-agnostic guard).
