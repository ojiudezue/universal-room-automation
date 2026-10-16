# PLANNING — Safety initial sensor pass (SAFETY-NO-INITIAL-SENSOR-PASS-1)

Card: `SAFETY-NO-INITIAL-SENSOR-PASS-1` ("After a restart or URA reload, Safety does not know
about a smoke/CO/leak detector that is still on"). Approved by the operator 2026-10-15 (board).
Status: **Rev 2**, folding the Tier-2 plan review `docs/reviews/plan-review/PLAN_REVIEW_safety_initial_sensor_pass.md` (verdict FIX-PLAN light; no CRITICAL or HIGH). Rev 1 was written 2026-10-16 (overnight pass).

## Rev 2: review disposition

| ID | Sev | Finding | Disposition | Where |
|---|---|---|---|---|
| P-01 | MED | D3 gate resolvable now: `acknowledge_notification` acks only the latest unacked CRITICAL (`database.py:4628-4651`, `ORDER BY timestamp DESC LIMIT 1`). | **Accepted, verified.** D3 code is REQUIRED; the "collapse to a test" branch is deleted. | §5 Q4, §7 D3 |
| P-02 | MED | A dominating PICK 1 option: honour a recovered unexpired cooldown. | **Accepted, verified** on branch: COOLDOWN recovery `notification_manager.py:4990-5014` sets `_alert_state=COOLDOWN` and `_active_alert_data{hazard_type,location}` and arms `_cooldown_expired` (`:3074-3085`), which calls `_re_evaluate_hazard` → `is_hazard_active` (`:3106`). New PICK 1(c) is the recommended default; the D3 accessor covers COOLDOWN. | §5 Q3, §7 D3, §11 |
| P-03 | MED | The pre-NM ordering hazard is reachable. | **Accepted.** Restated as reachable and pre-existing; proposed as a separate follow-up card. The pass is unaffected. | §9, §12 |
| P-04 | MED | A stuck-ON detector would unlock egress on every reload/restart once the toggle is ON. | **Accepted.** PICK 2(a) is kept with the risk named; new trip-wire deliverable D5 with a rung-1 knob. | §3, §7 D5, §8, §11 |
| P-05 | LOW | Invariant wording when a batch is in flight. | **Accepted.** INV-SEED(a) reworded. | §6 |
| P-06 | LOW | `seeded=0` does not discriminate. | **Accepted.** Log line gains `checked=N`; Live criterion requires N = discovered binary + CO fleet minus unavailable/unknown. | §7 D1 |
| P-07 | LOW | D3 needs a discharge statement. | **Accepted.** Discharge stated. | §7 D3 |


**Sequencing:** this plan is written against `feature/safety-nm-refire` (the
SAFETY-NM-REFIRE-UNWIRED-1 cycle, deploy held to Sun 10-18, ships as v5.103.65). All `file:line`
citations are against that branch (`git show feature/safety-nm-refire:<path>`). **The build starts
only after that branch merges to develop.** The builder re-checks every cited line against develop
before the first edit. That cycle explicitly defers this gap here
(`PLANNING_safety_nm_refire.md` §0 line 36, §0b lines 51-69, §5 line 234, §6 line 292, §8 line 368).

**Tier: Tier 2-DB (life-safety elevation).** See §8.

---

## 0. Summary

Safety learns about hazards only from state-change events. When URA reloads, or HA restarts and a
detector's state settles before Safety subscribes, a detector that is still ON sends no event. The
result is that `_active_hazards` stays empty: no hazard entity, no page, and the post-ACK re-fire gate
(`is_hazard_active`) answers False.

The fix: after the Coordinator Manager has set up every coordinator **and** the Notification Manager,
Safety reads the current state of every sensor it discovered once. For each sensor that currently
reads as a hazard, it queues one ordinary `Intent`, the same kind the state-change handler queues. The
existing pipeline (`evaluate` → `_process_sensor` → `_respond_to_hazard` → manager executes actions →
NM) does the rest, unchanged. This adds no new hazard logic and no new paging path.

---

## 1. Institutional context verified

### 1a. Prior-art scan (Tier 2+): REUSE or BUILD per piece

| Piece | Verdict | Evidence |
|---|---|---|
| Classifying a reading into a hazard | **REUSE** `_process_sensor` | `safety.py:1707-1825` (branch). Binary → `_handle_binary_hazard` `:1829`; numeric → `_handle_numeric_hazard` / `_handle_temperature` / `_handle_humidity`. |
| Registering the hazard, dedup, response actions, signal, NotificationAction | **REUSE** `_respond_to_hazard` | `:2466-2600`. `is_new` gate `:2487`; observation-mode gate `:2528`; `SIGNAL_SAFETY_HAZARD` dispatch `:2537-2548`; `AlertDeduplicator.should_alert` `:2577`; NotificationAction carries `hazard_type`/`location` (refire D1) `:2579-2592`. |
| Getting from a sensor reading to `_respond_to_hazard` with actions executed | **REUSE** the intent pipeline | `_async_sensor_state_changed` builds `Intent(source="state_change", entity_id, data={"state","old_state"})` and calls `manager.queue_intent` (`safety.py:1614-1633`). `queue_intent` `manager.py:927-945` → `_async_process_batch` `:947-1010` → `evaluate` `safety.py:1685-1705` → `_execute_action` (NotificationAction → `NM.async_notify`, `manager.py:1069-1094`). |
| Treating unavailable/unknown as "no reading" | **REUSE** `_UNAVAILABLE_STATES` | `safety.py:71` = `{"unavailable","unknown"}`; the event handler returns early on them at `:1589-1598`. |
| A sensor that comes up after setup (unavailable → on) | **REUSE**, already handled | `:1603-1614`: `old_state` in `_UNAVAILABLE_STATES` → `_evaluate_sensor_on_recovery`, then queues the intent. **The pass does not need to wait for late sensors.** The event path covers them (measured in §4). |
| A delayed "boot-settle" timer in Safety | **NONE EXISTS. Not built.** | grep `boot\|settle\|grace` in `safety.py` finds no startup grace. The only grace is the per-sensor numeric hold `:2040`. |
| NM boot-settle window | **REUSE, unchanged** | `NM_BOOT_SETTLE_S = 60` (`const.py:3476`), armed in `NM.async_setup` `notification_manager.py:1119-1123`, applied at `:1513-1525`. **Life-safety hazards bypass it** (`is_life_safety_hazard`, `:1516-1517`). Non-life-safety emits during the first 60 s collapse to one per `(coord, hazard_type)`. |
| Restore of `_active_hazards` across restart | **NONE EXISTS. Not built (deliberately).** | grep `restore` in `safety.py` finds only a comment at `:257`. `_active_hazards` is in-memory (`:1037`); `async_teardown` clears it (`:3463`). Reading the current state is better than restoring stale state: the detector is the source of truth (see §5 Q2). |
| NM recovery of an unacked CRITICAL / live cooldown across restart | **REUSE, unchanged** | `_recover_state_from_db` `notification_manager.py:4894-5016`: unacked CRITICAL under 24 h old → REPEATING (`:4964-4983`); unexpired cooldown → COOLDOWN plus `_cooldown_expired` timer (`:4990-5014`). |
| Hook point after NM is up | **BUILD (one call site per setup path)** | `manager.async_start` sets up coordinators in a loop (`manager.py:497-502`), then NM (`:505-514`). Safety re-enable path: `manager.py:1270-1273` (`async_setup` only, NM already up). No existing post-NM hook. |
| Safety method that queues the pass | **BUILD** `async_queue_initial_sensor_pass()` (name provisional) | No equivalent after grep of `safety.py` for `hass.states.get` loops. The only `hass.states.get` poll is the sweep backstop (§4-J writer b, `PLANNING_safety_hazard_clear_on_recovery.md`), and it reads only sensors already in a raising-set. |
| Kill switch | **BUILD** `SAFETY_INITIAL_SENSOR_PASS_ENABLED` (rung 1) | grep `INITIAL` in `const.py` / `safety.py`: no equivalent. |
| NM "already alerting this key" read (D3) | **BUILD, tiny, read-only accessor on NM** | `_active_alert_data` / `_alert_state` are private (`notification_manager.py:2502-2530`, `:166`). No public "which key is alerting" accessor found (grep `def .*alert.*key\|active_alert` in NM). |

### 1b. Prior planning docs consulted
- `docs/planning/PLANNING_safety_nm_refire.md` (branch copy, full): §0 D5 withdrawal (N1 is the origin of this card), §0b non-regression analysis, §6/§8 non-goals.
- `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md` (v5.103.61, shipped; rev-4 header and §4 read): the clear-hold, `_hazard_raising_sensors`, `_sensor_unavailable_since`, the life-safety re-arm `_LIFE_SAFETY_REARM_TYPES`. The pass has to fit these because it raises through `_respond_to_hazard`, which is where the contributor is registered (`:2484`).
- `docs/planning/AUDIT_restart_safety_classification.md`: Safety's restart findings (F1 anomaly baselines). It does **not** classify `_active_hazards`; this card is the missing row.
- `docs/QUALITY_CONTEXT.md` bug classes relevant here: #7 stale data source, #23 observation-mode gating, #53 computed-but-not-consumed / one missed site.

### 1c. Memory bodies pulled
- `feedback_suppression_needs_discharge.md`: any deferral needs a discharge. This plan adds **no** suppression. D3 suppresses only a *duplicate notification* when NM already owns the same key, and the discharge is NM's own REPEATING loop (latch-until-ack).
- `feedback_no_restart_during_sleep.md`: live validation needs a restart. Schedule it while the house is awake. Operator is travelling (10-15 → 10-18): ≤1 mid-day restart per day, batched.

### 1d. Design docs read
- `docs/Coordinator/SAFETY_COORDINATOR.md` (the refire cycle adds a §5 paragraph that names this gap; this cycle replaces that paragraph's "pre-existing gap" clause with the fix).

### 1e. Code surveyed (branch)
`safety.py` 1013-1100, 1214-1290, 1324-1480, 1563-1830, 1830-1960, 2466-2700, 2694-2820, 2965-2990, 3403-3436; `manager.py` 470-560, 920-1010, 1050-1110, 1255-1280; `notification_manager.py` 950-975, 1110-1135, 1385-1420, 1500-1530, 2502-2530, 3022-3060, 3087-3130, 4894-5016; `hvac.py` 1495-1505, 6338-6383; `security.py` 2041-2090; `coordinator.py` 1018-1045, 1755; `base.py` 270-282.

---

## 2. PRODUCER check: how `_active_hazards` is populated today

Every writer (grep `_active_hazards\[` / `.pop` / `.clear` in branch `safety.py`):

| # | Writer | Site | Trigger |
|---|---|---|---|
| W1 | `_respond_to_hazard` insert/overwrite | `:2494` | Every Hazard returned by `_process_sensor` via `evaluate`, which is reached **only from queued intents**. |
| W2 | `_async_periodic_check` flooding insert | `:2975` | 60 s tick, only if `_active_leak_sensors` is non-empty. That set is itself filled only by `_handle_binary_hazard` (`:1874`), so it is also event-fed. |
| W3 | `_pop_hazard_key` | `:2887` | Clear sweep, flooding clear (`:1855`). |
| W4 | `clear_hazard` / `clear_all_hazards` | `:3053`, `:3062` | Service / button. |
| W5 | `async_teardown` `.clear()` | `:3463` | Reload / unload. |

The only intent producers are `_async_sensor_state_changed` (`:1614-1633`) and the flooding periodic intent (`:2984-2990`). `async_setup` (`:1214-1290`) discovers sensors, subscribes, and starts timers, and reads no state. `_async_periodic_check` (`:2965-2992`) evaluates no sensor. **Confirmed: no writer seeds from current state.**

Dependency health (measured in §4):
- Configured binary sensors: 9 room leak sensors, 7 global leak sensors (overlapping), 2 global smoke-list sensors.
- Numeric: one CO sensor (`sensor.apollo_air_1_a87420_carbon_monoxide`), plus CO2/VOC.
- Live state of the binary fleet: 3 `unknown`, 2 `unavailable` (including the **only smoke detector**, `binary_sensor.smoke_sensor_s1_smoke`), 1 configured entity with **no recorder rows at all** (`binary_sensor.waterleak_sonoff_zigbee_ziribathroom_water_leak_2`).
- These are fleet-health findings, separate from this card (§9).

## 3. CONSUMER check: who acts on a hazard seeded at boot

Because the pass goes through `_respond_to_hazard`, **every** consumer of a new hazard fires exactly as it does on a live event. Per consumer, should a boot-seeded hazard trigger it?

| Consumer | Site | Trust / display | Fires at boot? | Why |
|---|---|---|---|---|
| Hazard entities (`binary_sensor.ura_safety_coordinator_safety_alert`, `_water_leak`, `_air_quality`, status/detail getters) | `get_safety_status` `:3112`, `get_water_leak_status` `:3152`, `get_air_quality_status` `:3183`, `get_affected_rooms` `:3214`; `_notify_entity_update` `:3271` | Display | **YES** | This is the core defect: the entity must show the live hazard. |
| NM page (NotificationAction → `async_notify`) | `:2577-2592` → `manager.py:1069-1094` | Trust (operator's eye) | **YES, once**, except D3 | Doctrine: silence is the defect. A hazard that began while HA was down was never paged. See Q4. |
| NM post-ACK re-fire gate `is_hazard_active` | `:3403-3436`; sole reader `notification_manager.py:3106` (`_re_evaluate_hazard`) | Trust | **YES** (state, not action) | Makes a cooldown recovered from DB (`:4990-5014`) re-fire correctly at expiry. This is the §0b discriminator. |
| `SIGNAL_SAFETY_HAZARD` → HVAC stop-fans | `hvac.py:1497-1503` → `_handle_safety_hazard` `:6338-6381` (smoke/CO CRITICAL, gated `CONF_HVAC_ON_HAZARD_STOP_FANS`) | Actuator | **YES** | A live smoke/CO condition wants fans stopped whether or not HA just restarted. Toggle defaults OFF (`base.py:270-276`); the key is absent from the live CM options, so it is **OFF in this house** (probe, §4). |
| `SIGNAL_SAFETY_HAZARD` → Security unlock egress | `security.py:2041-2090` (smoke/fire/CO CRITICAL, gated `CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS`) | Actuator, **security-sensitive** | **YES** | Same doctrine, and a real fire is exactly when egress must open. Risk: a detector stuck ON would unlock the doors at every boot. Today that risk is OFF in this house (toggle absent → default OFF); the binary fleet has **0 `on` rows** in recorder history (§4). See Q5. |
| `SIGNAL_SAFETY_HAZARD` → room chained automations / AI rules | `coordinator.py:1018-1045`, `:1755` (gating: neither toggle, deliberately) | Actuator | **YES** | Same reasoning; the room-level design comment (`:1021-1029`) already argues safety chains must always run. |
| CRITICAL response: emergency lights | `_critical_response` `:2694-2729` | Actuator | **YES** | One configured light (`light.smart_light_23031714641167590a0248e1e9c00955`, live CM options). |
| HIGH response: water shutoff, freeze/overheat ConstraintAction | `_high_response` `:2732-2766`, `_water_shutoff_actions` `:2819` | Actuator | **YES** | Valve close is idempotent and desired. No valve is configured live. Temperature is not seeded (Q1), so freeze/overheat cannot boot-fire from this pass. |
| Activity log, decision log, recent-events ring, anomaly `active_hazard_count` | `:2549-2565`, `:2594-2604`, `:2512`, `:2629-2690` | Display / analytics | **YES** | One row per seeded hazard. That is correct, because it is a real active hazard. Anomaly `active_hazard_count` gets one extra sample at boot (it is already sampled per new hazard). |
| Flooding escalation | `_check_flooding_escalation` `:1902`, periodic `:2965` | Trust | **YES** | Two leak sensors ON at boot escalate to FLOODING CRITICAL in the same batch, same as live. The single-sensor 15-min timer starts at seed time; `_leak_start_times` is in-memory, so pre-restart wet time is lost. That is accepted and pre-existing (§7). |

**Observation mode:** `_respond_to_hazard` suppresses signal, actions, and notification but still registers the hazard (`:2494`, `:2528-2535`). The pass inherits this unchanged.

---

## 4. Measure-before-build: probe results (HA recorder, read-only, 2026-10-16)

Probe: `ssh ha "python3 -"`, sqlite3 `mode=ro` on `/config/home-assistant_v2.db`, the last 20 `recorder_runs` (2026-10-08 → 10-15). For each run: offset of the first recorded state of `binary_sensor.ura_safety_coordinator_safety_alert` (proxy for "Safety platform up"; **not verified** to equal `Safety.async_setup` completion), and per monitored sensor the first state and first non-unavailable/unknown state.

| Signal (20 restarts) | Observed |
|---|---|
| Safety entity first state | **17-32 s** after run start |
| Zigbee leak sensors (5 of them) first `unavailable` | 19-258 s; first valid at **186-433 s** |
| Zigbee leak sensors: no valid state in 60 min | `upguestbathroom`, `ziribathroom`, `jayabathroom_water_leak` (not `_2`), `laundry`: **every restart** |
| Shelly flood `masterbathroomtoilet_flood` | valid at **16-23 s**, which overlaps Safety's 17-32 s |
| Smoke `smoke_sensor_s1_smoke` | `unavailable` at 4-21 s, **never valid** in 60 min, every restart; currently `unavailable` |
| CO numeric (Apollo ESPHome) | valid at 21-241 s (usually ≤ 37 s) |
| Any monitored binary sensor ever `on` in recorder retention | **0 rows** |
| `binary_sensor.madronewatermonitor_intelligent_leak` (ON at most boots) | **Not monitored** by Safety (not in any config list), so there is no seeding noise from it |

**What this means:**
1. On a full HA restart, the Zigbee fleet comes up **after** Safety subscribes. The `unavailable → on` event reaches `_async_sensor_state_changed` and is handled today, so the restart gap for Zigbee is narrower than the card implies.
2. The gap is real for (a) **URA reload / CM reload / Safety re-enable**, where states are already settled and no event fires, and (b) **fast WiFi/ESPHome devices** (Shelly flood, Apollo CO) whose states settle in the same 16-37 s window as Safety's setup, which is a race.
3. No settle delay is needed. Any sensor still unavailable at pass time is covered by its later recovery event. A delay knob would buy nothing.
4. Health problems in the life-safety fleet are bigger than this gap (§9).

---

## 5. Key design questions, answered

**Q1. Which sensors to seed?**
All discovered **binary** sensors (`_binary_sensors`: smoke-list + leak) whose current state is `on`. For numeric sensors, only types in `SAFETY_INITIAL_PASS_NUMERIC_TYPES = frozenset({"co"})` (rung 1), whose current reading parses as a float.
- Binary detectors are the real gap: they emit nothing while they stay ON.
- Temperature, humidity, CO2, and TVOC report changing floats every few minutes, so the event path re-raises them organically within minutes. Seeding them would start humidity/TVOC sustained timers and record ROC samples at boot, adding surface for little gain.
- CO is life-safety, and a steady CO reading may not change enough to emit.
- `off` binary states are **not** queued, so the path stays byte-identical to today when nothing is ON. `_handle_binary_hazard`'s off-branch would otherwise call `_record_sensor_recovery`/`_try_clear_if_quiet` on empty keys.

**Q2. Unavailable / unknown at boot?**
Skip them. Do not seed, do not stamp `_sensor_unavailable_since`, and do not restore a hazard from memory. That matches the event handler (`:1589`). When the sensor recovers, `:1603-1633` handles it (`_evaluate_sensor_on_recovery` plus intent). An `unknown → on` transition is covered because `unknown` is in `_UNAVAILABLE_STATES`. **Not seeding from a persisted hazard** is deliberate: the detector's current state is ground truth, and restoring a stale "smoke" key for a now-dead sensor would create a hazard nobody can clear except by the sweep backstop.

**Q3. Detector ON and acked before the restart: re-page or not?** (Rev 2, P-02)
Recommended (PICK 1(c)): **honour NM's recovered state, page otherwise.**
- If NM recovered an **unexpired COOLDOWN** for the same `(hazard_type, location)` (`notification_manager.py:4990-5014`), the seed registers the hazard **silently** (entity, actuators, `is_hazard_active`=True, no NotificationAction). At expiry, `_cooldown_expired` (`:3074-3085`) → `_re_evaluate_hazard` → `is_hazard_active` (`:3106`) returns True and re-fires. There is no early re-page.
- If there is no NM state for the key (the cooldown expired during downtime, or the hazard began while HA was down), the seed **pages once**. There is no permanent silence.

Rev 1 reasoning, kept for (a):
- NM drops COOLDOWN on entity restore (`notification_manager.py:965-971`) and recovers it from the DB only if it is unexpired (`:4990-5014`). If the cooldown expired while HA was down, nothing would ever re-page. That is precisely the operator-visible defect.
- Without a restart, the same still-ON acked hazard **does** re-page at cooldown expiry (refire D2). One page at boot keeps restart behaviour consistent with that.
- Cost of (a) alone: if HA restarts inside the 2-5 min cooldown, the operator gets the re-page a few minutes early, because a new CRITICAL pre-empts the cooldown (`_enter_alerting` cancels it, `:2513-2520`). Option (c) removes that cost.

**Q4. One page vs none at boot? Double-page risk.**
One page per seeded hazard, with one exception (D3): if NM already holds the **same** `(hazard_type, location)` in ALERTING/REPEATING/COOLDOWN (recovered unacked CRITICAL, `:4964-4983`), the seeded hazard registers in Safety (entity, `is_hazard_active`, actuators) but **does not emit a NotificationAction**.
- Reason: otherwise `_enter_alerting` writes a second unacked `notification_log` row and overwrites the slot. A later ack targets "latest unacked CRITICAL" (refire plan N4).
- That leaves the older row unacked, so the next restart within 24 h would recover it and repeat a hazard that may already be cleared. **Verified (P-01):** `acknowledge_notification` (`database.py:4628-4651`) acks only the single latest unacked CRITICAL row (`ORDER BY timestamp DESC LIMIT 1`). Ack does not cover the duplicate, so D3 code is required.
- NM boot-settle does not dedupe this case, because life-safety bypasses it (`:1516-1517`).
- Every seeded type (smoke, water_leak, flooding, carbon_monoxide) is in `NM_LIFE_SAFETY_HAZARDS` (`const.py:3391-3399`), so NM's boot-settle never collapses a seeded page.

**Q5. Boot-settle timing vs entity availability.**
No Safety-side settle. The pass runs once, after `NM.async_setup` returns. It must not run earlier: NotificationActions executed before `NM.async_setup` would reach an NM with `_boot_settle_until = 0.0` and un-recovered DB state (`notification_manager.py:481`, `:1119-1135`). Sensors not yet available are handled by their recovery events (§4). On the re-enable path (`manager.py:1270-1273`), NM is already up, so the pass runs right after `async_setup`.

**Q6. Race: an event for the same sensor lands around the pass.**
Both paths queue intents into the same batch queue. The second `_respond_to_hazard` for the same key and severity takes the `not is_new` branch (`:2487`, `:2496-2499`): counter only, no response. Order does not matter. With subscribe-before-pass (the existing order), no transition can be missed.

---

## 6. Falsifiable invariant

> **INV-SEED:** After Safety setup completes on any path (HA start, URA/CM reload, Safety re-enable) and NM is set up:
> (a) for every discovered binary sensor whose current state is `on`, and every discovered numeric sensor of a type in `SAFETY_INITIAL_PASS_NUMERIC_TYPES` whose current reading classifies as a hazard, the corresponding hazard key is present in `_active_hazards`, and `is_hazard_active(type, location)` is True, by the end of the first intent batch **that drains the pass intents** (if a batch is in flight, the pass intents are rescheduled into the next one, `manager.py:1011-1019`);
> (b) **no** hazard key is ever created from a sensor whose current state is `off`, `unavailable`, or `unknown`, or that is not discovered;
> (c) each seeded life-safety hazard produces **at most one** NotificationAction from the pass, and **zero** if NM already holds the same `(hazard_type, location)` in ALERTING/REPEATING/COOLDOWN;
> (d) with no discovered sensor in a hazard state, the pass produces no intent, no action, and no log row (byte-identical to today).
>
> Falsified by any reachable path, including the re-enable path and observation mode, where (a)-(d) fails. Example: a reload with `binary_sensor.waterleak_hob_zigbee_kitchen_water_leak = on` that leaves `water_leak:Kitchen` absent after the first batch, or a recovered REPEATING `smoke:<loc>` row plus a second unacked `smoke:<loc>` row written by the pass.

---

## 7. Deliverables

### D1: `Safety.async_queue_initial_sensor_pass()` (BUILD, `safety.py`)
- Iterate `self._binary_sensors` and `self._numeric_sensors` (filtered to `SAFETY_INITIAL_PASS_NUMERIC_TYPES`).
- Read `hass.states.get(eid)`. Skip `None` and `_UNAVAILABLE_STATES`. For binary, skip anything other than `"on"`. For numeric, skip unparseable values.
- Queue `Intent(source="initial_pass", entity_id=eid, data={"state": s, "old_state": None}, coordinator_id="safety")` via `manager.queue_intent`, exactly like `:1621-1633`.
- No-op when `not self._enabled` or `SAFETY_INITIAL_SENSOR_PASS_ENABLED` is False.
- Log one INFO line with counts (`checked=N seeded=S skipped_unavailable=M`), where `checked` = discovered binary sensors + `SAFETY_INITIAL_PASS_NUMERIC_TYPES` sensors whose state was readable and not unavailable/unknown. This is the live discriminator (P-06).

**Wire-in anchors (mandatory, per `feedback_wire_in_anchor_mandatory`):**
- (i) `manager.async_start`, immediately after the NM setup block (`manager.py:505-514`), guarded so that NM failure does not block the pass. If NM setup failed, still seed: the entity state matters even without paging.
- (ii) `manager` enable path, after `await coordinator.async_setup()` at `manager.py:1273`, only for `coordinator_id == "safety"` (or a `hasattr` hook).

Both calls go through a single helper so there are no two hand-rolled paths.

#### Acceptance criteria
- **Verify:** A Safety set up with `binary_sensor.leak_x = on` (state set **before** setup, no subsequent event) has `water_leak:<loc>` in `_active_hazards` after `async_start` plus one batch. The **discriminating contrast:** the same fixture with D1's call site removed leaves it empty, which is what distinguishes the fix from "the event path happened to fire".
- **Verify:** Sensors at `off` / `unavailable` / `unknown` / missing produce zero intents (spy on `queue_intent`).
- **Verify:** The pass runs after `NM.async_setup`: the call-order spy shows the NM setup call before the first `initial_pass` intent.
- **Test:** `test_initial_pass_seeds_on_binary_without_event`, `test_initial_pass_skips_off_unavailable_unknown_missing`, `test_initial_pass_runs_after_nm_setup`, `test_initial_pass_runs_on_safety_reenable`, `test_initial_pass_respects_kill_switch`, `test_initial_pass_observation_mode_registers_no_actions`, `test_initial_pass_two_leaks_escalate_flooding`, `test_initial_pass_co_numeric_seeded_temperature_not`.
  - Tests must drive the **real** `CoordinatorManager.async_start` and the real `_async_process_batch`, not a fake coordinator (v5.8.0 incident lesson).
- **Mutation anchors (C):** delete call site (i) and `test_initial_pass_seeds_on_binary_without_event` goes RED; delete call site (ii) and `..._on_safety_reenable` goes RED; drop the `_UNAVAILABLE_STATES` skip and `..._skips_...` goes RED.
- **Live:** After the deploy restart, the HA log has one `Safety initial sensor pass: checked=N seeded=0 ...` line. N must equal the count of discovered binary + CO sensors that are not unavailable/unknown at that moment, cross-checked by a `hass.states` read at the same time.
  - A pass that runs but classifies nothing shows `checked=0`. That would be a FAIL, not "all clear".
  - Also: `binary_sensor.ura_safety_coordinator_safety_alert` is `off`.

### D2: Post-ACK re-fire survives restart (verification of the §0b discriminator; no new code beyond D1)
#### Acceptance criteria
- **Verify / Test:** `test_refire_after_restart_with_still_on_detector`. Simulated restart: NM DB has an acked smoke row with an unexpired cooldown, the smoke sensor is `on` before setup, and there is no event. At cooldown expiry, exactly one `async_notify` comes from `_re_evaluate_hazard` with `hazard_type="smoke"`, plus a new `notification_log` row.
  - **Contrast:** with D1's call removed, `is_hazard_active` is False and NM goes IDLE (no row). That is the refire plan §0b discriminator, in-suite.
- **Live:** In-suite only. Inducing a live smoke ON plus a restart in an occupied house is not acceptable. Recorded as in-suite-only in the README.

### D3: No duplicate unacked row when NM already owns this key (REQUIRED, P-01; widened to COOLDOWN, P-02)
- Add a read-only NM accessor `owns_hazard_key(hazard_type, location) -> bool` (name provisional). It is True if `_alert_state` ∈ {ALERTING, REPEATING, COOLDOWN} and `_active_alert_data` matches the key.
- In `_respond_to_hazard`, **only for `source="initial_pass"` hazards**, skip appending the NotificationAction when the accessor is True. Everything else (registration, entities, actuators, signal) is unchanged.
- Threading the source into `_respond_to_hazard` needs one parameter on the existing call at `:1702`. The builder must keep the state-change path byte-identical: the default is `source=None`, which means today's behaviour.
- **Discharge (P-07):** the suppression is discharged by NM's own state machine. REPEATING keeps paging until acked; COOLDOWN re-fires at expiry through `is_hazard_active`, which the seed made True. If NM leaves that state without an ack (for example NM disabled mid-episode), the hazard stays in `_active_hazards`, so the next state-change relapse or the post-ACK re-fire pages normally. The skip is a one-shot at pass time, not a standing mute.
#### Acceptance criteria
- **Verify / Test:** `test_initial_pass_does_not_double_page_recovered_repeating`: NM recovered REPEATING `smoke:Kitchen`; the pass seeds `smoke:Kitchen` → zero new `notification_log` rows, `_active_hazards` has the key, the emergency-light action is still emitted.
  - **Contrast:** recovered REPEATING `smoke:Garage` + seeded `smoke:Kitchen` → exactly one new row (a different key is not suppressed).
- **Test:** `test_initial_pass_honors_recovered_cooldown` (P-02): NM recovered an unexpired COOLDOWN for `smoke:Kitchen`; the smoke sensor is `on` before setup.
  - Expect zero rows at seed time, then exactly one `_re_evaluate_hazard` re-fire at expiry.
  - **Contrast:** an expired cooldown (no NM state) gives one row at seed time.
- **Test:** `test_state_change_path_unaffected_by_d3`: the event path still pages when NM is REPEATING on the same key (today's behaviour preserved).
- **Mutation (C):** force the accessor to False and the double-page test goes RED.
- **Live:** none possible without a live hazard (in-suite only).

### D5: Stuck-detector trip-wire (P-04)
When the pass seeds a **CRITICAL** hazard from a sensor whose `last_changed` predates the pass by more than `SAFETY_INITIAL_PASS_STUCK_SENSOR_H`, Safety emits one additional NotificationAction.
- Severity HIGH; `hazard_type="safety_sensor_stuck"`, which is not life-safety, so NM boot-settle collapses repeats inside the 60 s window.
- Text along the lines of "<sensor> has read ON since <time>; check for a stuck detector."
- It also logs a WARNING.
- The seeded hazard and its responses are **not** suppressed. This is a signal for the operator, not a gate.
- Why: once the egress toggle is ON, a stuck smoke/CO detector unlocks the doors on every reload/restart, and reload/restart storms have run ~5×/night. This makes that visible on the first occurrence.
#### Acceptance criteria
- **Test:** `test_initial_pass_stuck_sensor_tripwire_fires`: `last_changed` = now − 48 h with the knob at 24 h → one stuck notification plus the normal hazard response.
- **Contrast tests:** `last_changed` = now − 1 h → no stuck notification. Knob = 0 → no stuck notification.
- **Mutation (C):** invert the age comparison and the test goes RED.
- **Live:** in-suite only (no detector is ON).

### D4: Docs
- `SAFETY_COORDINATOR.md` §5: replace the "pre-existing gap" clause with the initial-pass description, the consumer table summary (§3), and the measured boot timings (§4).
- Note in `AUDIT_restart_safety_classification.md`: `_active_hazards` row = RESET → **RE-DERIVED from current state** (not persisted, by design).
- Correct the NM docstring claim at `notification_manager.py:957-958` ("live sensors will re-trigger alerts if hazards persist"). It was false before this cycle and becomes true only with D1, so cite D1.

---

## 8. Numbers and knobs

| Name | Value | Rung | Why | Kill-switch semantics |
|---|---|---|---|---|
| `SAFETY_INITIAL_SENSOR_PASS_ENABLED` | `True` | 1 (module const, `safety.py`) | Life-safety behaviour. Turning it off must require review, and the operator has no legitimate reason to turn it live. | `False` = today's behaviour exactly (no pass). |
| `SAFETY_INITIAL_PASS_NUMERIC_TYPES` | `frozenset({"co"})` | 1 | Which numeric types to seed. Widening it changes boot paging, so it is reviewed. | Empty set = binary-only. |
| `SAFETY_INITIAL_PASS_STUCK_SENSOR_H` | `24` | 1 | Age threshold for the D5 stuck-detector trip-wire. Safety-adjacent; changing it should be reviewed. | `0` = trip-wire disabled. |
| (no settle-delay knob) | n/a | n/a | Measured unnecessary (§4): late sensors arrive via recovery events. | n/a |

No new config-flow fields and no entities.

## 9. Non-goals
- **Fleet health** (out of scope, card each): `binary_sensor.smoke_sensor_s1_smoke` unavailable at every boot and now (the only real smoke detector); 4 Zigbee leak sensors never valid post-restart; the configured `..._ziribathroom_water_leak_2` has no recorder rows; `binary_sensor.gas_zigbee_kitchen_gas` sits in the **smoke** list and so raises `smoke:` not gas/CO; the CO-alarm binaries (`*_co_alarm_detected`, camera-derived) are not monitored. Operator / config-first actions, not code.
- Persisting `_active_hazards`, `_leak_start_times`, or flooding timers across restart.
- NM multi-alert tracking (`NM-MULTI-ALERT-TRACKING-1`), D5 revival, the cadence knob (`SAFETY-UNACKED-REPEAT-CADENCE-KNOB-1`).
- Seeding temperature / humidity / CO2 / TVOC.
- Any change to `_repeat_alert`, the NM boot-settle window, or `is_hazard_active` semantics.
- A periodic re-poll of sensor state (the sweep backstop already exists for raising contributors).
- The pre-NM-setup ordering hazard (P-03). **It is reachable and pre-existing.** Safety subscribes in its own `async_setup` (`manager.py:497-502`) while later coordinator setups still await (HVAC waits on Presence). The batch window is 100 ms (`manager.py:50`, `:933-945`). So a fast device event (the Shelly flood is valid at 16-23 s, §4) can run `_execute_action` → `NM.async_notify` before `NM.async_setup` (`:505-514`) and its DB recovery, and write a row that recovery then shadows. The pass is unaffected: it runs after NM setup, and a hazard already raised makes the seed `not is_new`. Proposed as a follow-up card (§12).

## 10. Tier and review framings

**Tier 2-DB, elevated** (standing policy: life-safety plus cross-coordinator ripple: Safety → NM → HVAC / Security / room chains).
- No schema change, but D3 changes when `notification_log` rows are written.
- Considered and rejected: Tier 3. The pass reuses the single existing emission path, so there is no new emission site to miss. D3 is one guarded skip.
- Escalate to Tier 3 if plan review finds a second path into `_active_hazards` that the pass must also cover.
- One adversarial plan review before build (Tier 2+ rule).

Three build reviews, framing-disjoint:
- **A — local correctness + config extremes:** the skip set (`on` only; unavailable/unknown/None/unparseable), the numeric type filter, kill switch, observation mode, `_enabled` False, empty fleet (byte-identical), two leaks ON → flooding, blocklisted sensor, room/global precedence duplicates.
- **B — lifecycle / ordering / cross-coordinator:**
  - Pass strictly after `NM.async_setup` on boot, and after `async_setup` on re-enable; no pass on disable.
  - Reload/teardown interplay with `_unsub_listeners`; event and pass racing the same sensor (`is_new` idempotence).
  - NM REPEATING / COOLDOWN recovery × pass (D2/D3).
  - Every `SIGNAL_SAFETY_HAZARD` consumer behaves as on a live event (hvac `:6338`, security `:2041`, coordinator `:1018`); re-grep for new consumers.
  - `notification_log` row count per scenario.
- **C — test authority via real per-site mutation:** both wire-in call sites, the unavailable skip, the D3 accessor, the numeric filter. Each must turn a named test RED. Tests use the real `CoordinatorManager`.

**Live validation:**
- After the restart, the log line from D1 shows `seeded=0`, and the hazard entities read `off`.
- A URA **reload** (not a restart; check `feedback_parent_entry_reload_watchdog_hazard` first and prefer a Safety disable/enable toggle) produces the log line again.
- An optional controlled leak test (operator wets a leak puck, then toggles Safety off/on while it stays wet) expects `water_leak:<room>` back in `_active_hazards` and one page. Operator-gated, not while away.

## 11. Open questions for the operator (PICKs)

1. **Boot page for an already-acked, still-ON detector.**
   - (a) Always re-page once at boot. Early re-page inside the cooldown.
   - (b) Seed silently and let only NM recovery page. Leaves an acked hazard with an expired cooldown permanently silent.
   - (c) **Recommended (P-02):** honour a recovered unexpired cooldown (seed silently; NM re-fires at expiry through `is_hazard_active`), and page once when there is no NM state. No early re-page, no permanent silence.
2. **Actuators at boot (door unlock, fan stop, emergency lights, valve).**
   - (a) Same as a live event. **Recommended**: doctrine, and both door/fan toggles are OFF here today.
     - **Named risk (P-04):** if `security_on_hazard_unlock_egress` is turned ON, a stuck-ON smoke/CO detector unlocks every egress door on **every** reload/restart, including while the house is AWAY. A live event does this only once per episode.
     - Mitigation: the D5 trip-wire pages "possible stuck detector" the first time.
   - (b) Page-only at boot, no actuators. Adds a source-gated branch inside `_respond_to_hazard` (a second path; Bug Class #53 risk).
3. **D3 duplicate-row guard:** no longer a pick. Required after P-01 verification.
4. **D5 stuck-detector trip-wire threshold:** 24 h default (rung 1), 0 disables. **Recommended: 24 h.**
5. **Fleet-health cards** (dead smoke detector, 4 never-valid leak pucks, a ghost entity, gas sensor in the smoke list): card them now? **Recommended yes.** Higher value than this cycle.

## 12. Follow-ups (proposed cards, not minted here)
- **SAFETY-PRE-NM-SETUP-NOTIFY-RACE-1** (P-03): a state-change NotificationAction can reach `NM.async_notify` before `NM.async_setup` and its DB recovery (`manager.py:497-514`). It is reachable with fast WiFi/ESPHome devices. Fix direction: hold NotificationActions until NM is set up, or set up NM before coordinators. That is a separate cycle.
- Fleet-health cards listed in §9 (dead smoke detector, never-valid leak pucks, ghost `_ziribathroom_water_leak_2`, gas sensor in the smoke list).
