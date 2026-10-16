# Audit: battery-reserve surface, ground truth vs. Reserve Write Governor plan Rev 3.1

**Date:** 2026-10-16 (00:00-01:00 CDT). **Mode:** read-only. Not committed.
**Framing:** start from live behaviour and code, then check the plan against it. This is not a re-run of plan reviews 1-3.
**Plan under audit:** `docs/planning/PLANNING_reserve_write_governor.md` Rev 3.1.

Evidence sources used: HA recorder (`home-assistant_v2.db`, `call_service` events and the states table, 7 days), live `core.config_entries`, the live `tou_rates.json`, the live `sensor.ura_energy_coordinator_battery_strategy`, the URA DB (`ura_activity_log`, `decision_log`), and source at develop `f7c2775b3`. Docs read: the EC manual (§2.3-2.6a), the explainer, and the listed memory bodies.

---

## 1. Live ground truth

### 1.1 Configuration (live `core.config_entries`, CM entry)

| Key | Live value |
|---|---|
| `energy_reserve_soc_entity` (local, witness) | `number.enpower_482348004678_reserve_battery_level` |
| `energy_cloud_reserve_oracle_entity` (**write leg**) | `number.iq_battery_hacs_battery_reserve` |
| `energy_reserve_soc` | 10 |
| `inclement_partial_hold_reserve_floor` | 50 |
| `ENERGY_CLOUD_FIRST_WRITES` | `True` (`energy_const.py:518`). Static: `_write_failover_by_surface` is set once at `energy_battery.py:551-555` and never flips at runtime. |

**Every URA reserve write targets the cloud entity.** All 470 reserve `set_value` calls in the 7-day recorder window name `number.iq_battery_hacs_battery_reserve`. None name the local entity. The local entity is also `unavailable` for long stretches (87 state flips in 7 days; `unavailable` right now).

### 1.2 TOU (live `/config/universal_room_automation/tou_rates.json`, utility PEC)

- Shoulder (Mar-May, Oct-Nov, which is the current season): off_peak 00-17, mid_peak 17-21, off_peak 21-24. **There is no peak period.**
- Winter (Dec-Feb): off 00-05, mid 05-09, off 09-17, mid 17-21, off 21-24.
- Summer (Jun-Sep): off 00-14, mid 14-16, peak 16-20, mid 20-21, off 21-24.
- Midnight is off_peak→off_peak in every season, and so are the season rollovers (Nov 30→Dec 1, Feb→Mar, May→Jun, Sep→Oct). `check_period_transition` (`energy_tou.py:620-632`) sees no edge at midnight or at a season change. Transitions happen only at in-day hour boundaries.
- **Blind de-escalation fires only on `peak` / transition into `peak`** (`energy_battery.py:5632`). It cannot be reached live until June 2027. Plan edge case 4 can be proven only in the test suite.

### 1.3 Reserve producers: what they do live

Measured: 7-day recorder `call_service` events for `number.set_value` on the reserve. Service-data key order tells two code paths apart. `{"value","entity_id"}` comes from `_execute_service_action` (`energy.py:7752-7756`) or the CM (`energy.py:7203-7204`). `{"entity_id","value"}` is the dict literal in `force_redispatch` (`energy_battery.py:6817-6820`).

| Producer | Code | Live evidence (7 d) | Notes |
|---|---|---|---|
| `_result` (sole strategy emit, 2-pt deadband) | `energy_battery.py:6352-6398` | Most of 430 timer/CM dispatches. Example: 10-14 11:52→15:42, value 10 every 5 min (49 sends) while the cloud entity read 6.0 for 6.5 h | Deadband reads the **cloud write-leg** state (`_get_entity(..., role="write")` `:6357-6360`). If the cloud entity is stale, `_result` re-sends every tick. |
| Off-peak drain / hold | `energy_battery.py:6236-6276` | Strategy-sensor history: "Off-peak hold — SOC 9.0% <= target 10%" at 10-15 04:20 → dispatched **8** at 04:27:59. Also 6 on 10-14 | **Hold writes reserve = int(SOC), below `reserve_soc`=10.** This is legitimate. The partial_hold clamp is an inline `max()` at `:6224`/`:6262`, not a `_floor_reserve` wrap, so the "8 wraps" are not the full enforcement inventory. |
| Arbitrage CHARGE/HOLD | `energy_battery.py:3892+` (via `_result`) | 90 at 10-13 15:39 and 10-14 15:47 (charge window 14:30, boundary 17:00). Released to 10 at 17:00:05 both days (at-boundary tick, +5 s) | Works as the manual describes (§2.3 steps 2-3). |
| Attain / afternoon ramp | via `_result` | 15 at 10-15 13:56, 20 at 16:31, released at 17:00:05 | — |
| EVSE overlay (update-in-place + append) | `energy.py:5239-5540` (append `:5515`) | Not separable in the recorder from `_result` (same key order). The append leg emits **every charging tick with no deadband** (`:5515`). | This is why the plan needs a gate at all. The update-in-place leg rewrites the existing `_result` / blind dict, so it adds no literal and the lint cannot see it; C1 sees the value. |
| DP drain-precedence | `energy.py:5542+`, `energy_drain_precedence.py` | No direct writer (grep: no `set_value` / `async_call` / `_execute_service_action` for reserve). Floor rides the overlay through `_dp_decision_soc`. | Verified safe. No row path needed. |
| Blind de-escalation | `energy_battery.py:5632-5690` (literal `:5664`) | Unreachable in shoulder/winter. Live right now: Envoy blind, reason "Envoy unavailable — holding (no commands issued)", `actions=[]` | — |
| Inclement floors | `_floor_reserve` `:3855` + 8 wraps + inline off-peak clamps | Live: `allow_discharge`, `reserve_floor`=10, partial-hold knob 50 | — |
| `force_redispatch` (pending-watchdog self-heal) | `energy_battery.py:6713-6852`, caller `energy_write_verify.py:2331-2360` | **40 redispatches in 7 d.** Examples: 10-14 16:02/16:22/16:52 (90), 10-15 14:16/14:31/15:01 (15), 16:51 (20) | See O-3: three 90 redispatches while the cloud entity already read 90. |
| Evaluate (CM, TOU-transition) path | `energy.py:1367-1376` → `_evaluate_battery` `:7150-7221` → `manager.py:1001-1051` | Cannot be told apart from the timer in the recorder. It fires only when a CM evaluation runs before the at-boundary tick consumes `_last_period` (+5 s). That is rare. | It shares `_tou._last_period` with the timer (`energy.py:1370` vs `:6364`). Whichever runs first consumes the edge. |
| Fill-priority buffer (v5.103.63) | `energy_pool.py` EV switch only | Branch diff `merge-base..304bfe64d^2` has no `reserve` / `set_value` line | Verified safe. It does not touch the reserve. |
| Non-URA writers | — | None found in 7 d: every reserve call matches URA code shapes | The Enphase cloud revert/lag is real, though. See O-4. |

**Volume (the plan's §3 bound, measured):** 430 dispatch + 40 redispatch in 7 days, which averages about 67/day. The peak was 142/day (10-13). The plan's ≤288/day bound holds. With the R3-01 gate, re-sends to a stale cloud entity **will** each produce a row (pre_state ≠ value). On a 10-14-style day that is about 50 extra rows. They are truthful, and the volume is acceptable.

### 1.4 Where code, docs and live disagree

| # | Claim | Where | Ground truth |
|---|---|---|---|
| D-1 | The strategy entity is `sensor.ura_battery_strategy` | Plan R1 carry-over and live AC; plan review 1 R1-03 | **The entity does not exist** (ha_get_state 404). The real entity is `sensor.ura_energy_coordinator_battery_strategy`. |
| D-2 | `log_activity` "does not use the write queue" | Plan R2-08 / §Row; review 2 R2-08 | **False.** `log_activity` (`database.py:6233`) uses `async with self._db()`, and `_db()` **is** the write-queue submitter (`database.py:523-541`: "Writes go through a single-worker queue"). Rows are serialized through `_write_queue`, one queue item per row. That is safe, and the volume is tiny. |
| D-3 | `radar_tuning.py:276` uses a variable domain, so the lint does not match it | Plan INV-G1 and §4; review 3 R3-02 | **False.** `radar_tuning.py:274-279` is `async_call("number", "set_value", {...}, blocking=False)`, both literals, inside `async_send_radar_settings`. A package-wide lint built to the plan goes **RED on HEAD**. |
| D-4 | URA writes the local `number.enpower_..._reserve_battery_level` | Memory `project_battery_soc_envoy_not_span.md`, `project_enphase_coupling_tier.md`; `docs/ENERGY_MANAGEMENT_EXPLAINER.md:34` | Writes are cloud-first (manual §2.6; `energy_battery.py:831-835`; 470/470 live calls go to the cloud entity). The memory and the explainer are stale. |
| D-5 | "Current through v5.18" | EC manual header | The code is at v5.103.x. The manual is accurate on cloud-first and the at-boundary tick, but it does not cover the governor-adjacent machinery (stand-down, `force_redispatch`, DP). |
| D-6 | "8 `_floor_reserve` wraps" are the partial_hold enforcement | Plan §Institutional / Non-goals | The 8 wraps are correct (`:3926,3949,3991,4715,4769,5004,5952,6098`; `:6687` is narration). There is **also** inline partial_hold clamping in the off-peak branch (`:6224`, `:6262`). This is not a governor defect, because the governor does no fold, but D should not take "8 wraps" as the full inventory. |

---

## 2. How the governor build could change live behaviour or break an invariant

| ID | Sev | Finding | Repro / evidence | Required plan change |
|---|---|---|---|---|
| **G-1** | **MED** (INV-G3 risk) | **C3 sits inside the `try` around the service call.** The plan places C3 "after the success log (`:6822`)", which is inside the `try:` at `energy_battery.py:6816-6825`. The helper never raises, but the **call expression** can: `self._coord._record_reserve_dispatch(...)`. If `_coord` is absent, which is the standard test wiring ("Test wiring: assign `strat._coord = fake_coord`", `energy.py:319`), or is a fake without the method, the `AttributeError` lands in `except Exception` at `:6826`. That branch records a **false** `dispatch_failed` (anomaly + NM), **returns before the ledger stamp** (`:6845-6852`), and the pending watchdog keeps the old `commanded_at`. | A unit test with `BatteryStrategy` and no `_coord`, or a coord stub, calls `force_redispatch("reserve_soc")` with a fresh desire. Today the ledger is stamped. With C3 inside the try, `record_dispatch_failed` fires and `_last_reserve_level` is unchanged. | Put C3 (success) **after** the try/except, after step 5's ledger stamp, as `coord = getattr(self, "_coord", None)` plus `getattr(coord, "_record_reserve_dispatch", None)` inside its own `try/except: debug`. Put `redispatch_failed` after `record_dispatch_failed` in the except branch, with the same guard. Add a mutation row: "C3 raises inside the call → ledger still stamped, no dispatch_failed". |
| **G-2** | **MED** (validation would mis-judge) | The live AC compares against "the live state of the configured reserve number entity" and against `command_trail` "on `sensor.ura_battery_strategy`". The configured `energy_reserve_soc_entity` is the **local witness**, which is often `unavailable` and never receives URA writes. The sensor name is wrong (D-1). | Live now: the local entity is `unavailable`; the cloud entity reads 10.0; `command_trail.reserve_soc.commanded.value`=10 on `sensor.ura_energy_coordinator_battery_strategy`. | Rewrite the live AC to say: compare `value` against the **write-leg** entity, i.e. `entity_id` in the row = `number.iq_battery_hacs_battery_reserve`, resolved by `_get_entity("reserve_soc_number", role="write")`. Use `sensor.ura_energy_coordinator_battery_strategy` → `command_trail.reserve_soc.commanded.value`. Allow for cloud lag of about 90 s: on 10-15, the 17:00:05 send was reflected at 17:01:33. |
| **G-3** | **MED** (lint RED on HEAD, builder confusion) | D-3: `radar_tuning.py` is a literal-form writer. | AST walk over the package (this audit) finds 12 matches. 11 are the plan's set. The 12th is `('radar_tuning.py','async_send_radar_settings','call',274)`. | Add `("radar_tuning.py", "async_send_radar_settings", "non_reserve", 1)`. Drop the "variable domain" known-limit example and replace it with a real one, or with none. |
| G-4 | LOW | **R2-08 text is wrong (D-2).** The behaviour is still safe: one write-queue item per row, about 67 dispatch rows/day measured. During a VACUUM or worker-restart window rows buffer (`database.py:530-541`). At shutdown they fast-fail (`:543-548`). Neither path back-pressures dispatch, because the helper is fire-and-forget. | — | Correct the mechanism text. The design is unchanged. |
| G-5 | LOW | **The `pre_state` comparison type is unspecified.** HA state is the string `"10.0"`. Comparing the raw string to `int 10` is never equal, so the gate never fires and every steady overlay re-send logs. Volume rises to ≤288/day, so this is not a behaviour change, but the gate-mutation test could pass for the wrong reason. | — | Specify `pre_state = battery._get_state_float(target)` (`energy_battery.py:881`), compare `int(round(pre_state)) == int(value)`, and treat None as "write the row". |
| G-6 | LOW | **C1 inherits the tap filter's hole.** `energy.py:9097-9099`: `if target and reserve_eid and target != reserve_eid: return`. When `reserve_eid` is None (no reserve role on a second install), **any** `number.set_value` in `decision["actions"]` passes. Today `_result` / overlay / blind emit nothing when the role is unset (`:6390`, `:5336`, `:5658`), so it is unreachable. It becomes reachable as soon as anything adds a non-reserve number action to the battery decision. | — | C1 should require `reserve_eid` to be truthy as well (row only). Leave the existing tap behaviour untouched. |
| G-7 | LOW | **`hold_owner` records precedence, not provenance.** `_resolve_hold_owner` (`energy_write_verify.py:1738-1766`) returns `evse_battery_hold` whenever the overlay is active, even when the **value** came from the strategy. Example: an arbitrage HOLD at 80 and an EVSE hold at 45 give `effective=max(80,45)=80`, labelled `evse_battery_hold`. | `energy.py:5401-5408` | Document the field as "highest-precedence active subsystem". Optionally add `desire` vs `value` vs `evse_hold_soc` so provenance can be derived. Do not change `_resolve_hold_owner`. |
| G-8 | LOW | **The ordering claim "C1 reads the current call's decision" can fail under interleaving.** `_evaluate_battery` is not guarded by `_cycle_in_flight` (`energy.py:6326-6336` guards only the timer). The timer suspends between `determine_mode` (`:6390`) and dispatch (`:6591`) at several awaits (`_account_arbitrage_cycle` `:6431`, breaker actions `:7382`). A CM batch that consumes a TOU edge in that window re-runs `determine_mode` (`:7155`), which overwrites `_last_reserve_level_desired` and `_last_inclement_decision`. The timer's C1 then reads the evaluate tick's `desire` and floor. The row fields are wrong; the dispatch is unchanged. | Requires a CM evaluate within the seconds a timer tick is in flight across a boundary. Rare. | Qualify the §Ordering text. If you want, capture `desire` and the decision locally in the timer before the first await and thread them in, following the house "capture before first await" rule (the plan already does this for `_soc_untrusted`, `:6401`). |
| G-9 | LOW | **The `floor_ok=0` live query can false-positive** from any partial_hold path that legitimately writes below `max(reserve_soc, floor)` and is neither wrapped nor inline-clamped. None was found in this audit's read of the off-peak, arbitrage and overlay paths. There is no partial_hold history in the 7-day window (live `allow_discharge`), so it is not live-provable now. | — | The AC should say: "0 expected; any hit is investigated against the inclement-hardening site table before being called a governor defect". |

### Verified safe (no change needed)

- **The A/B byte-identical premise.** Everything C1/C2/C3 add is a pure read: `_resolve_hold_owner`, `_evse_hold_state`, `_dp_transition_floor` and `_inclement_partial_hold_floor` (`energy_write_verify.py:1630-1766`) are getattr-only. `_get_entity` has one side effect, a once-per-key INFO log set in `_cloud_write_target` (`energy_battery.py:868-877`). Under the live config the cloud key is set, so that branch never runs. `hass.states.get` is pure. The DB write is fire-and-forget. G-1 is the one exception.
- **The tap is called for every action on the timer path** (`energy.py:7387-7398`), and only when `not self._observation_mode` (`:6582`). Observation mode therefore produces neither a timer dispatch nor a C1 row, which is consistent.
- **C2 truthfulness.** CM `ConflictResolver` (`manager.py:97-137`) drops an action only when two actions target the same device. Energy is the only coordinator that targets the reserve entity, and one decision carries at most one reserve action, because the overlay updates in place. A C2 row for an undispatched value would need a second reserve producer in another coordinator. None exists.
- **Cloud-first target resolution.** C2 must resolve with `role="write"`, the way `_cfg_eid` does at `:7186-7191`. The routing flag is static (`energy_battery.py:551-555`), so the target cannot change mid-tick.
- **Restart.** The memo is RAM-only, so the first post-boot write is always logged. `wv_commanded_ledger` is a KV key restored through `restore_energy_state_with_age` with a 10 h gate (`energy.py:1948-1968`). The governor does not touch it.
- **Season, midnight and DST.** No TOU edge happens at midnight or at a season change (§1.2). The governor has no time-of-day logic. The gate memo carries no time component, so there is no day-boundary blindness (bug class "day-boundary-blind TOU" does not apply).
- **Using ActivityLogger instead of the direct `log_activity`** would add dedup windows (30-300 s, `activity_logger.py:27-31`) that **drop** rows, which would break INV-G2. The plan's choice of direct `db.log_activity` is correct.
- **`_tap_write_verifier` has exactly one production caller** (`energy.py:7394`), so the keyword-only `pre_state=None` is safe.

---

## 3. Producers and consumers the plan missed

- **`radar_tuning.async_send_radar_settings`** is a literal `number.set_value` writer to radar device numbers, not the reserve (G-3). It is missing from `RESERVE_SET_VALUE_WRITERS`.
- **The off-peak inline partial_hold clamps** (`energy_battery.py:6224, 6262`) are a floor-enforcement site that the plan's "8 wraps" inventory omits. They have no governor impact, but they belong in D's enumeration and in the `EC-INCLEMENT-HARDENING-1` site table.
- **The CM path is not observation-gated** (pre-existing, Bug Class #23). `_evaluate_battery` (`energy.py:7150-7221`) never checks `self._observation_mode`, and `CoordinatorManager._execute_action` (`manager.py:1035-1051`) executes regardless. In observation mode, a TOU-transition reserve or CFG write reaches hardware through the CM. `force_redispatch` is also ungated. The governor makes this visible (C2/C3 rows during observation mode), which is a benefit. It should be carded, not fixed here.
- No other reserve writer exists. The whole-package AST walk found 12 literal writers (11 + radar). There is no `SERVICE_SET_VALUE` import in the package, `services.yaml` has no reserve service, and the DP and fill-priority modules have no reserve writer.

---

## 4. Boundary cases (day/night, TOU, twice-per-tick, CM)

1. **At-boundary tick (+5 s) vs CM evaluate.** Both call `check_period_transition`, and the first caller consumes `_last_period`. Live, 17:00:05 sends on 10-14 and 10-15 show the at-boundary tick winning. If the CM wins instead, then: (a) C2 writes `dispatch_queued`; (b) the timer runs `determine_mode` with `tou_transition_into=None`. **Pre-existing:** the arbitrage-chunk reset on entry to off_peak and the blind "transition→peak" leg key on `tou_transition_into` (`energy_battery.py:5631`; chunk reset, manual §2.3), so that edge is missed for that boundary. This is not caused by the governor. Card it as `EC-TOU-EDGE-DOUBLE-CONSUMER-1`.
2. **Twice per tick, determine_mode.** When the CM path fires, `determine_mode` runs twice within seconds, once from the CM and once from the timer. Each dispatch is real, so there are two rows (C2 + C1, different verbs, the gate does not collapse them). That is truthful. See G-8 for the interleaving case.
3. **Cloud lag at boundaries.** At 10-15 17:00:05, 10 was sent while the cloud read 20. At 17:01:07 the timer sent 10 again because the cloud still read 20. The cloud reflected 10 at 17:01:33. The plan writes two rows (pre_state 20 ≠ 10 both times). That is correct, and the live AC must tolerate it (G-2).
4. **Night drain / hold below reserve_soc.** Writes of 8 and 6 at 04:28 and 07:04 are legitimate under allow_discharge. The row has `inclement_floor=None` and `floor_ok=None`, so nothing is flagged. Under partial_hold the inline clamp raises the value to ≥ floor, so `floor_ok=True`.
5. **Midnight and season rollover:** no edge, no writes caused by the rollover (§1.2).
6. **Restart mid-arbitrage:** the latch persists through `_save_evse_state` (eager). The first post-boot reserve write gets a row, because the memo is empty.

---

## 5. Observations outside governor scope (card them, do not fix in this cycle)

- **O-1** Pre-existing #23: the evaluate/CM path and `force_redispatch` ignore observation mode (§3).
- **O-2** Pre-existing: TOU edge double-consumer (§4.1).
- **O-3** On 10-14, `force_redispatch` re-sent 90 at 16:02, 16:22 and 16:52 while `number.iq_battery_hacs_battery_reserve` already read 90 (changed 15:47:36). The pending watchdog judged divergence against something other than the cloud entity state, possibly the local witness, which went unavailable repeatedly that day. **Unexplained.** Probe with `pending_write_stuck_state` history.
- **O-4** On 10-14, 09:08→15:47, URA sent 10 forty-nine times while the cloud entity stayed at 6.0. Neither stand-down nor the `_result` skip engaged. Either the cloud entity stalled or Enphase did not apply the writes. The governor will make this visible as about 50 drift rows.
- **O-5** Doc drift D-4 and D-5: fix the memory bodies (`project_battery_soc_envoy_not_span.md`, `project_enphase_coupling_tier.md`), `ENERGY_MANAGEMENT_EXPLAINER.md:34`, and the manual header.
- **O-6** Corrections to plan reviews: R1-03 (wrong entity_id), R2-08 (wrong write-queue claim), R3-02 (wrong radar claim). Do not re-assert them.

---

## 6. Verdict: **FIX-PLAN** (text edits only; the design holds)

The governor design is sound against ground truth. It writes only, it is fire-and-forget, every read is pure, and the three call sites cover every live reserve writer (430 dispatches + 40 redispatches in 7 days, all through `_result` / overlay / `force_redispatch` / CM). The volume bound holds as measured. No live behaviour changes **except through G-1**.

**Required plan changes before build:**
1. **G-1:** move C3 out of the service-call `try`, use `getattr` to reach `_coord` and the method, and add the corresponding mutation/test row.
2. **G-2:** rewrite the live AC to use the write-leg cloud entity and `sensor.ura_energy_coordinator_battery_strategy`, with a cloud-lag tolerance of about 90 s.
3. **G-3:** add the `radar_tuning.py` row to `RESERVE_SET_VALUE_WRITERS` and fix the INV-G1 known-limits text.
4. **G-4 to G-9 (LOW):** correct the R2-08 mechanism text; specify the numeric `pre_state` comparison; have C1 require `reserve_eid`; document `hold_owner` semantics; qualify the §Ordering text (or capture before the first await); add an investigation clause to the `floor_ok` AC.

**Cards to mint:** O-1 (observation-mode leak on the CM path and `force_redispatch`), O-2 (TOU edge double-consumer), O-3 (redispatch while the cloud already compliant), O-4 (stale cloud vs repeated re-send), O-5 (doc/memory drift).
