# PLANNING: EC reserve oracle, phase 2 (local witness primary, cloud corroborator)

Card: **EC-ENPHASE-CONNECTIVITY-RESILIENCE-1** (phase 2). Instances folded in: `INSTANCE_2026_10_23_reserve_stuck_98`, `INSTANCE_2026_10_22_stale_cloud_false_critical`, `INSTANCE_2026_10_14_reserve_pending_episode`.
Operator approved planning 2026-10-23. **Tier 3.** Status: **rev 2.2** (2026-10-24, D0 P5 NO-GO: stream tier dropped, see the rev 2.2 markers), build approved 2026-10-24 (Q1-Q5 as recommended). Rev 2.1 (2026-10-23) text below. Rev 2.1 applies the four must-fixes of the rev-2 re-review (appended at the end; see the **Rev 2.1 disposition** rows in section 13). Rev 1 got two framing-disjoint plan reviews (both FIX-PLAN-FIRST; appended below, kept verbatim). Rev 2 resolves every finding; see the **Rev 2 disposition** table at the end of section 13. Next: a short re-review of the rev-2 deltas (completeness reviewer re-runs the site enumeration against the new stamps), then D0, then build, four build reviews, operator checkpoint before deploy.

Evidence base:
- `docs/planning/AUDIT_envoy_reserve_98_alert_2026_10_23.md` (the stuck-98 incident)
- `docs/planning/AUDIT_envoy_reserve_oracle_history_2026_10_23.md` (7.6-day history, behavioural scorecard)
- `docs/planning/AUDIT_envoy_mqtt_trust_measurement.md` (stream witness, criterion 3.7) — added rev 2

---

## 0. Problem in one paragraph

URA writes the battery reserve to the Enphase **cloud** number (`number.iq_battery_hacs_battery_reserve`, cloud-first since H1, `energy_const.py:533`). The same cloud number is also used for two decisions. (1) The send/skip deadband in `_reserve_action` (`energy_battery.py:7024-7060`) compares the target to the cloud value. (2) The "Envoy write not applied" CRITICAL (`energy_write_verify.py:780-789`) compares the command to the cloud value. Since 10-19 the cloud number has gone stale for hours at a time, in 4 episodes covering about 23% of wall-clock time. While it is stale it disagrees with what the gateway enforces. The local Envoy sensor (`sensor.envoy_482543015950_reserve_battery_level`) predicted battery behaviour in 554 of 558 decisive minutes; the cloud number predicted it in 2. Two failures follow:
- **Stuck reserve.** On 10-23 the cloud read 10 while the gateway enforced 98. The release to 10 was deadbanded against the stale 10, so nothing was sent. The battery idled at 98-100% while the house imported about 6 kW at mid-peak for about 4.5 h. Even if URA had sent 10, `enphase_ev` drops a write equal to its stored *selected* value (`/config/custom_components/enphase_ev/number.py:384-388`, key `battery_selected_backup_percentage`, `coordinator.py:6714`), so the send would have done nothing.
- **False pages and churn.** CRITICAL "not applied" pages fire while the gateway already matches the command (10-22, 10-23). The inverse case (episode B, 10-19/20: cloud 98, gateway 10 = desire) caused about 100 identical re-sends of 10.

---

## 1. Institutional context verified

### 1.1 Documents read
| Doc | How | Relevance |
|---|---|---|
| `AUDIT_envoy_reserve_98_alert_2026_10_23.md` | full | Incident mechanism, site list, manual unstick |
| `AUDIT_envoy_reserve_oracle_history_2026_10_23.md` | full | Scorecard 554/558, local unavailable 7.4%, low-SOC wobble, same-value drop (section 4.3), recommended design (section 6) |
| Card EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 (`kanban.data.yaml:971`) | full | Original phase-2 scope, instances, relevance check 10-16 |
| `ARC_energy_coordinator_resilience.md` | full | Governor shipped v5.103.66 (step 1). This card is outside the arc; its blocker is cleared |
| `PLANNING_ec_enphase_resilience_and_p1_adjust.md` | sections 4, 6 (R2, R6), 9, 10 | Phase-2 R-items; R6 supersession; I-W1 "witnesses only tighten" |
| `PLANNING_enphase_cloud_reliance.md` | headers + D2 | D2 dwell-gated divergence pattern; reused shape for D4 |
| **`PLANNING_reserve_write_governor.md`** (rev 2) | sections on INV-G1, C1/C2/C3 rows, known limits | The four reserve dispatch points all write a `reserve_write` row through `_record_reserve_dispatch` (`energy.py:9651`); CM path row is DEFERRED with unseen outcome (`energy.py:7420-7455`). Rev 2 uses that single choke point for the new attempt stamp |
| **`quality/tests/test_reserve_write_chokepoint_lint.py`** + `RESERVE_SET_VALUE_WRITERS` (`energy_const.py:2692-2702`) (rev 2) | read | AST lint counts `"number.set_value"` calls/constants per function. The nudge helper returns a value only, so the allowlist is unchanged (acceptance criterion in D2) |
| **`PLANNING_ec_reserve_witness_fix.md`** (rev 2) | skim + witness section | 10-18 registry resolution of the local witness; operator ruling "keep ±2" — the deadband constant is named at 2, not retuned |
| **`PLANNING_behavioral_write_verify.md`** (rev 2) | skim | `_check` / sweep / self-heal origin; status vocabulary |
| **`PLANNING_envoy_local_witness_and_solar_follow.md`** §1.6, Cycle A4 (rev 2) | read | Stream reserve witness `sensor.envoy_stream_backup_reserve` (MQTT `meters.backup_soc`) |
| **`AUDIT_envoy_mqtt_trust_measurement.md`** criteria 3.2, 3.7 (rev 2) | read | Run 2 (09-25..27, 28.7 h clean): stream up 98.65% of native-down time; **3.7 reserve witness PASS** (10/10 changes matched, stream led by 1-32 s). Only one window; never measured inside a stale-cloud episode |
| `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` | 2.5, 2.6, 2.6a | Cloud-first write model |
| Memory `reference_ec_reserve_verifiable_backout_knob.md` | full | `is_reserve_verifiable` semantics. Not touched (N3) |
| Memory `project_envoy_boot_incident_2026_06_12.md` | full | No new boot-time reads |
| Memory `project_enphase_coupling_tier.md` | full | Reserve = primary lever; writes go to cloud entity |
| Memory `project_inclement_arbitrage_wait_floor_gap.md` | full | INV-1 floor fold must survive (C9 exception only) |
| Memory `project_ev_drain_precedence_cycle.md` | full | EVSE hold backstop; its release relies on `_reserve_action` |

### 1.2 Code surveyed (end-to-end for the named functions; rev 2 re-verified on `develop` c9e8f0015)
`energy_battery.py`: `_reserve_action` 6983-7066, `_result` 7068-7160, attain-floor bypass 5290-5322, blind trigger 6091 (`if not envoy_avail and soc is None`) and blind de-escalation 6118-6200, `force_redispatch` ~7540-7660 (set_value 7579/7597, failure record ~7596, rows 7613/7647, step-5 ledger 7632-7634), `current_park_floor` 2458-2484, `_get_entity` / `_cloud_write_target` 868-900, `_write_failover_by_surface` 593-605, `_read_current_commanded_reserve` 2478-2510.
`energy_write_verify.py`: `__init__` 144-235, `is_reserve_verifiable` 240-331, `_local_entity_for` 374 (Enpower-number fallback 419-427), `_envoy_reserve_sensor_eid` 431, `schedule` 485-670 (self-heal starvation 586-621), `_check` 675-789, `_conduct_check_reserve` 2043, `_sweep_surface` 839-1044 (REVERTED coalesce 995-1006, pending suppression 1007-1021), `_commanded_ledger` 1125-1131, `_compare` 1173-1210 (tolerance `<= 2.0` at ~1207), `_local_reserve_witness_state` 1626-1649, `_effective_reserve_desired` 1787-1816, `_pending_watchdog_reserve` 2198-2410 (spacing gate 2270-2285), `command_trail` 2569-2595.
`energy.py`: `_evaluate_battery` 7375-7455 (called on TOU transition at 1472, skipped in observation mode at 1464-1470), `_apply_evse_battery_hold` 5424-5725 (clamp fallback 5655-5667, ledger stamps 5630-5632 and 5719-5721), timer dispatch loop 7650-7668, `_record_reserve_dispatch` 9651, `_tap_write_verifier` ~9840-9903 (ledger stamp 9876-9883 **before and independent of** `dispatch_result.ok`; row status 9890-9895; `schedule` 9903), KV restore 2064-2065, KV persist 2116/2416.
`energy_const.py` 500-560, 2670-2702. `enphase_ev` v5.1.5 (Samba mount): `number.py:340-400`, `control_updates.py:20-115,170-240`, `coordinator.py:6714-6720`, `sensor.py:4029-4121` (from the reviews; not re-read in rev 2).

### 1.3 Live / DB facts gathered for this plan (2026-10-23 evening)
- `sensor.iq_gateway_hacs_system_profile_status` attributes, live: `pending: true`, `requested_reserve_percentage: 10`, `selected_reserve_percentage: 10`, `effective_reserve_percentage: 12`, `pending_requested_at: 2026-10-24T00:30:05Z`. The local sensor read 10 from 00:30:13. **`pending` was still true about 50 minutes after the gateway applied the value.** One reading; D0-P3 measures it.
- URA `anomaly_log` `battery_write_failed`: 9 rows since 10-12. 6 `control_change_pending`, 3 `out_of_range`. `enphase_ev` raises `ServiceValidationError(control_change_pending)` for a second change in the same group inside `CONFIRMATION_WINDOW_S = 600` while the first is unconfirmed (`control_updates.py:25,71-76`).
- (rev 2, from review 2, `control_updates.py:170-177`, ~92) While a control update is open, the number's *state* returns the confirmed snapshot taken at `begin`, while the drop key `battery_selected_backup_percentage` returns the pending value. **So the cloud number's state is not the drop key**, exactly in pending windows.

### 1.4 REUSE / BUILD verdicts (greps re-run 2026-10-23; surfaces: `const.py`, `energy_const.py`, `config_flow.py`, `options_flow.py` (no hits), entity platforms, `domain_coordinators/*`, `docs/planning/*`, memory)

| Piece | Verdict | Evidence |
|---|---|---|
| Local reserve witness read | **REUSE** `_envoy_reserve_sensor_eid` (431) directly, NOT `_local_reserve_witness_state` (1626), which goes through `_local_entity_for` and silently falls back to the frozen Enpower number (419-427). New thin resolver `WriteVerifier._resolve_reserve_witness(battery) -> (eid, tier)` reports which tier resolved | grep `reserve_battery_level\|_local_reserve_witness_state\|_envoy_reserve_sensor_eid` |
| **Stream reserve witness `sensor.envoy_stream_backup_reserve`** (rev 2) | **rev 2.2 (D0 P5 NO-GO): NOT BUILT, PARKED.** Revival trigger: stream add-on re-enabled AND a 3.7-style reserve-change match measured. No resolver, no flag (a disabled flag would be dead code on a retired feed). Rev 2.1 text: **REUSE, gated on D0-P5.** Not referenced in code today (grep `stream_backup_reserve` in `custom_components/`: 0 hits; planning only). Prior plan A4 proposed exactly this; trust audit 3.7 PASS. If P5 passes it is witness tier 2 (used only when native is unavailable); if not, PARKED with P5 as revival trigger | §1.1 rows |
| Cloud reserve read | **REUSE** `_get_entity("reserve_soc_number", role="write")` + `_get_state_float`, read inside `_reserve_action` and passed into the helper | 7020-7027 |
| Commanded ledger `_last_reserve_level` | **REUSE, semantics UNCHANGED** (tap still stamps on a raised call). See D5 / section 4.3 for the decision and consumer enumeration | `energy.py:9876-9883` |
| **Landed-request stamp `_reserve_last_ok_value/_at`** (rev 2) | **BUILD, new, small.** The value of the last reserve dispatch whose service call did not raise. No equivalent: `_last_reserve_level` is an intent ledger stamped on raise; grep `last_ok\|landed\|_reserve_last_` in energy*.py: 0 hits | |
| **Attempt stamp `_reserve_last_attempt_value/_at`** (rev 2) | **BUILD, new, small.** Stamped at the single choke point `_record_reserve_dispatch` (`energy.py:9651`), which all four reserve dispatch points already call (timer tap 9890, CM path 7450, `force_redispatch` 7613/7647). `_last_reserve_level_at` is not usable: it changes only when the value changes (9880) and is not stamped on the CM path | grep `_record_reserve_dispatch` |
| Desired reserve stamp | **REUSE** `_last_reserve_level_desired` (single writer `_reserve_action:7017`) | |
| Post-overlay effective desire (rev 2) | **REUSE** `WriteVerifier._effective_reserve_desired` (1787; already used by `force_redispatch` 7546). It folds EVSE hold, inclement partial_hold floor, DP drain floor | |
| SOC | **REUSE** `_read_soc_via_resolver` (1651) | |
| Deadband 2 | **REUSE value, NAME it** `RESERVE_DISPATCH_DEADBAND_PCT = 2` (inline literal 7059 today; operator "keep ±2" ruling in `PLANNING_ec_reserve_witness_fix.md`) | grep `DEADBAND` |
| Trust rule | **BUILD, new, one owner:** `WriteVerifier.trusted_local_reserve(battery, target, soc) -> (value: float|None, source: str)`. `BatteryStrategy` calls it via `self._write_verifier` (7037); `_write_verifier is None` = untrusted. D3 and D4 call the same method | grep `_reserve_reference\|enforced_reserve\|trusted_local`: 0 hits |
| Same-value-drop bypass ("nudge") | **BUILD, new** pure helper `_nudge_value(target) ` + trigger predicate in D2. Returns a value only (no service call) | grep `same_value\|nudge`: 0 relevant hits |
| Cloud-stale classification in the verifier | **EXTEND** `_check` MISMATCH (757-789), `_sweep_surface` REVERTED (989-1044), `schedule` self-heal starvation (586-621). New `STATUS_CLOUD_STALE` | grep `STATUS_` |
| Enforced-vs-desired dwell trip-wire | **BUILD, small**, shaped like the churn trip-wire (`energy_write_verify.py:189-192`) and the per-day `_maybe_fire_nm` latch. Compares local to the **post-overlay** effective desire | |
| `control_change_pending` | **EXTEND** `record_dispatch_failed` (1286) → DEFERRED classification; `WriteStatus.DEFERRED` exists | 6 live rows |
| Polling `pending` attribute | **PARKED behind D0-P3** | |
| `selected_reserve_percentage` attr as the drop key (rev 2) | **NOT USED.** Equivalence to `battery_selected_backup_percentage` is asserted by review 2 from `sensor.py:4121` but would add a third oracle whose own staleness is unmeasured. D2 keys on URA's own landed-request history instead (field-agnostic) | |
| Local write-failover retirement | **MOVED OUT** (N1) | |
| New knobs | All rung 1 (section 7) | |

### 1.5 Config-first check
- No knob changes the deadband reference or the CRITICAL oracle. `CONF_RESERVE_VERIFIABLE_MAX_AGE_S` touches neither.
- Operator workaround for a live episode: write a reserve at least 2 away from the cloud value; URA writes desire 5 min later (proven 10-23 00:23Z). It needs a human to notice, and nothing alerts on a stuck reserve today.
- Integration reload does not help (cloud came back stale after the 00:22 reload).
- **Verdict: code is required.**

---

## 2. Falsifiable invariants

Definitions used below. **target** = URA's folded, clamped pre-overlay desire passed to `_reserve_action`; it is **never derived from an enforced (hardware) reading** (rev 2: the attain-bypass base is intent, D1.4). **effective desire** = `WriteVerifier._effective_reserve_desired(battery)` (post-overlay: EVSE hold, inclement partial_hold floor, DP drain floor). **trusted** = `trusted_local_reserve` returns a value (D1.1). All times use `dt_util.utcnow()`.

**INV-R1 (convergence while the witness is trusted).** Assume local trusted throughout, no stand-down pinned on the effective desire, observation mode off, and no `control_change_pending` raise in the window. Then the enforced reserve (local reading) is never `RESERVE_DISPATCH_DEADBAND_PCT` or more away from the **effective desire** for longer than `RESERVE_CONVERGENCE_BOUND_S` = 2 × 300 s decision tick + `RESERVE_RESEND_MIN_GAP_S` (900) + `RESERVE_APPLY_LAG_ALLOWANCE_S` (900) = **2400 s**. Holds in any reachable path, including cloud reading the target (stale-equal), cloud reading anything else, and the integration silently dropping the first send (the nudge path).
*Falsifier:* a recorder trace with local trusted and |local − effective desire| ≥ 2 for more than 2400 s, during which **no** `reserve_write` row was dispatched after the first 1200 s (rev 2 wording per R1-L2; a nudge row legitimately differs from both desire and cloud).

**INV-R2 (no false "not applied").** No `write_verification_failed` (reason `mismatch` or `self_heal_starvation`) and no `write_reverted` anomaly or NM fires for the reserve surface while the trusted local witness is strictly within `RESERVE_DISPATCH_DEADBAND_PCT` of the commanded value. In that state the verifier records `STATUS_CLOUD_STALE` and emits at most one `reserve_cloud_oracle_stale` anomaly per (site, desire) episode; never CRITICAL, never paged.
*Falsifier:* a `notification_log` CRITICAL "Envoy write not applied/reverted/self-heal loop: reserve_soc" row inside a window where |local − commanded| < 2. (At exactly 2 the page still fires, by design: R2-M4.)

**INV-R3 (witnesses only tighten).** When no witness is trusted, every decision equals pre-cycle behaviour (deadband against the cloud, CRITICAL from the cloud), with exactly two additive exceptions, both of which can only **add** sends: (a) the landed-request term (D1.3 rule L) and (b) the attain-bypass base change (D1.4), which fixes a pre-existing lowering leak and has its own kill switch. The re-send gap (D1.3 rule G) gates **only** sends caused by the local or landed terms, never a cloud-caused send, so it cannot suppress a pre-cycle send. **(rev 2.1, RG-H1) Raise timing:** whether or not a witness is trusted, no reserve **raise** (candidate value above the trusted local + deadband, or with no trusted witness above `_reserve_last_ok_value`) is ever sent later than pre-cycle code would send it: rule G never gates a raise, so a failed or dropped raise is retried on the next tick exactly as the pre-cycle cloud compare would. Nothing lowers a reserve below the folded floor except the target = 100 nudge (C9).
*Falsifier:* a test with no trusted witness where a send or page that pre-cycle code emits is suppressed, or a value below `_tick_reserve_floor` is emitted (other than C9).

**INV-R4 (bounded writes).** For one stable **lowering or same-value** desire (raises are exempt from rule G and keep the pre-cycle every-tick retry, still inside the 12/h cap), the new paths add at most one dispatch per `RESERVE_RESEND_MIN_GAP_S` (900 s) — at most 4 per hour, counting dropped and deferred dispatches — and the first nudge occurs no earlier than one gap after the first plain send unless the cloud state already equals the target. Never more than `DEFAULT_BATTERY_WRITE_CHURN_MAX_PER_H` (12) per hour from all reserve paths combined. (rev 2.1, RG-L1) `force_redispatch` (watchdog, 900 s ladder on `_last_reserve_level_at`) is not gated by rule G; a D1 send and a watchdog retry can collide inside the Enphase 600 s window. Pre-existing; the resulting `control_change_pending` raise is **accepted and absorbed by D5** (DEFERRED, no page), and it counts toward the 12/h all-paths cap. D0-P2 replay plus the synthetic pending-episode test set the expected counts.
*Falsifier:* two dispatches of the same (target or nudge) value, caused by the local or landed term, less than 900 s apart.

---

## 3. Measure before build: D0 (FIRST deliverable, go/no-go gate)

One-shot read-only script over the HA recorder (`/config/home-assistant_v2.db`, retained since 10-16) and the URA DB, `ssh ha "python3 -" < script.py`. Report appended as section 13.

| Probe | Question | Gates |
|---|---|---|
| P1 low-SOC regime | For every minute with SOC and native local numeric: the distribution of (local − last commanded) against (SOC − commanded) **and** (local − SOC). Where does the ratchet start (lower edge) and how far above SOC can the ratchet reading go (upper edge)? | `RESERVE_LOCAL_LOW_SOC_MARGIN_PCT` (assumed 3) and `RESERVE_LOCAL_RATCHET_SPAN_PCT` (assumed 20; 10-17 data: local 10-26 at SOC 4-9). If the wobble appears with SOC above commanded + 5, or above SOC + 30, D1.1 is redesigned before build |
| P2 replay | Replay D1 (all rules, including gap G and the nudge trigger) minute by minute over 10-16..now using recorded local, stream, cloud, SOC, and `ura_activity_log` desire / ledger / `reserve_write` rows. Count predicted dispatches per hour and per desire change against actual. List every minute where INV-R1 would still be violated, and every minute where D4 would have fired under pre-cycle code (episodes C, D expected) and under the new rule (expected none). **Limitation stated:** the recorder starts 10-16, after the 10-12..14 pending episodes, so P2 cannot exercise the pending shape; that is covered by the synthetic test `test_pending_episode_bounded_writes` (D1) | INV-R4 (go if no hour exceeds 4 new-path dispatches per stable desire and none exceeds 12 total); episodes A-D release within 2400 s |
| P3 pending attribute | Is `pending` / `requested_reserve_percentage` stored in recorder attributes? If yes: duration of each `pending: true`, does it clear, overlap with stale-cloud episodes and with local-matches-command minutes | D6 un-park (expected: stays parked) |
| P4 nudge landing and apply lag | For the 10-23 00:23 operator write and URA's 00:30 write: local apply lag. Across all `reserve_write` rows since 10-16: local apply-lag distribution (p50/p90/p99) and whether any second write within 600 s raised `control_change_pending` | `RESERVE_RESEND_MIN_GAP_S` (900) must be ≥ 600 and ≥ measured p90; `RESERVE_APPLY_LAG_ALLOWANCE_S` (900) must be ≥ measured p99. If p99 > 900, both bound constants are raised before build |
| **P5 stream witness** (rev 2) | Does `sensor.envoy_stream_backup_reserve` still exist and record? Over 10-16..now: agreement with native local when both numeric (match within 1 pt, lead/lag), availability during native-down minutes, and its value **inside episodes A-D** (does it track the gateway, not the stale cloud?) | GO → D1.1 tier 2 enabled (`RESERVE_STREAM_WITNESS_ENABLED = True`). NO-GO or entity missing → tier 2 ships disabled (`False`) and is PARKED with P5 as the revival trigger; C4 residual stands |

**Gate rule:** build is dispatched only after D0 reports P1, P2 and P4 inside bounds. If P2 shows an episode the rule would not have released, stop and revise.

---

## 4. Producer and consumer checks

### 4.1 LOCAL native `sensor.envoy_<serial>_reserve_battery_level` (official `enphase_envoy`)
- **Producer:** Envoy local API via the core integration; reports what the gateway enforces. Resolved by `_envoy_reserve_sensor_eid` (431-480), registry-anchored on the configured SOC entity.
- **Health:** unavailable 7.4% of 181.6 h, longest outage 461 min. Change-only reporting, no age signal. At SOC near/below commanded it reads a ratcheted effective floor (10-17: local 10-26 at SOC 4-9). No "available but frozen" case found for this sensor.
- **Fallback hazard:** `_local_entity_for` falls back to the frozen Enpower number (419-427), constant 10.0. D1.1 resolves via `_envoy_reserve_sensor_eid` directly and never trusts that fallback.
- **Consumers today:** `_pending_watchdog_reserve` 2219 (trust: retries); `_witness_compare` 1061 (anomaly); `pending_write_stuck` payload 2347 (display); **`command_trail` three-way display 2569-2595 (display; rev 2, R1 enumeration)**. All unchanged.
- **New consumers:** `trusted_local_reserve` → `_reserve_action` (trust: send/skip, D1); `_local_confirms` at three verifier sites (trust: page or not, D3); D4 dwell (trust: alert).

### 4.1a STREAM `sensor.envoy_stream_backup_reserve` (rev 2)
- **Producer:** Envoy MQTT stream `meters.backup_soc`, ~1 Hz, independent transport (survives native polling outages 98.65% in the 09-25..27 window).
- **Health:** 3.7 PASS on 10/10 changes in one 28.7 h window; never measured inside a stale-cloud episode; partial-fleet hazard 3.8 applies to SOC, not observed on the reserve field. D0-P5 measures.
- **Consumers today:** none in URA code.
- **This cycle:** tier-2 witness inside `trusted_local_reserve` only when native is unavailable and `RESERVE_STREAM_WITNESS_ENABLED`; same low-SOC guard applies. `source = "stream"`.

### 4.2 CLOUD `number.iq_battery_hacs_battery_reserve` (`enphase_ev`)
- **Producer:** `current_control_value(coord, "battery_reserve", "reserve", battery_selected_backup_percentage)` (`number.py:362-372`). During an open control update its state is the confirmed snapshot from `begin` (`control_updates.py:~92,170-177`), so it can differ from the drop key. Goes stale for hours while available; cause unknown.
- **Health:** stale about 23% of wall-clock since 10-16. Unavailable 0.2%.
- **Consumers:**

| Site | Use | Trust/display | Changed by this cycle? |
|---|---|---|---|
| `energy_battery.py:7024-7027` `_reserve_action` | deadband compare | TRUST | **YES (D1)**: cloud value passed to the helper; used as reference only when no witness is trusted, and as one input of the nudge trigger |
| `energy_battery.py:5302-5319` attain-floor bypass `_hw` | base of `max(floor, base)` | TRUST | **YES (D1.4)**: base becomes URA intent (desire stamp → ledger → `_hw`), not a hardware reading |
| `energy_battery.py:6132-6135` blind de-escalation `_wl` | base when no desire stamp | TRUST | **NO.** Blind = `not envoy_avail and soc is None` (6091). R1-L1: a blind tick can still have a healthy native or stream witness; by design the blind path keeps the pre-cycle cloud compare (INV-R3 holds; blind rules are separately reviewed Stage-A machinery) |
| `energy_battery.py:2497-2504` `_read_current_commanded_reserve` | status attr | DISPLAY | no |
| `energy.py:5514-5519` overlay target | target id | n/a | no |
| `energy.py:7421-7451`, `:7642-7650` governor rows `pre_state` | audit column | DISPLAY | no |
| `energy_write_verify.py:519` `schedule` unavailable N-strike | cloud unavailable | TRUST | no |
| `energy_write_verify.py:702-789` `_check` | not-applied CRITICAL | TRUST | **YES (D3)** |
| `energy_write_verify.py:863-1044` `_sweep_surface` | OK / STALE-retire / REVERTED | TRUST | **YES (D3)** |
| `energy_write_verify.py:586-621` `schedule` self-heal starvation | loop NM | TRUST | **YES (D3)** |
| `energy_write_verify.py:279` `is_reserve_verifiable` | blind guard | TRUST | **NO** (N3) |

### 4.3 Commanded ledger `_last_reserve_level` / `_last_reserve_level_at` — semantics UNCHANGED (rev 2 decision)
- **Producer:** timer tap stamps the dispatched value **before and regardless of** `dispatch_result.ok` (`energy.py:9876-9883`; verified rev 2); EVSE overlay stamps (5630-5632, 5719-5721); `force_redispatch` step 5 stamps only on success (returns earlier on raise, 7586-7625); KV restore (2064-2065). The CM path does not stamp (governor known limit).
- **Decision (R1-H1 / R2-H2):** the tap is **not** changed. Option (a) "don't stamp on not-ok" was rejected because every consumer below would see a different value after any FAILED write, which is a new Tier-3 ripple outside this card, and because the CFG ledger beside it is documented as a fail-closed intent ledger that deliberately stays stamped on failure (`energy.py:9913-9915`, B2). Instead the cycle adds the **landed-request stamp** (4.5), which is what D1 rule L and the D2 trigger actually need. The retry claim moves to that stamp.
- **Consumers (complete, rev 2 grep `_last_reserve_level\b`), all unchanged by this cycle except the D2 +1 effect:**

| Consumer | file:line | Effect of D2 nudge (ledger = target+1) |
|---|---|---|
| sweep / `_check` supersession `_commanded_ledger` | `energy_write_verify.py:1125-1131` | commanded = t+1; `_compare` tolerance 2 → match; benign |
| `_conduct_check_reserve` | `energy_write_verify.py:2043` (reads `_commanded_ledger`) | +1, within its deadband; benign |
| pending watchdog | `energy_write_verify.py:2209` | compares local (t+1) to ledger (t+1); converged |
| EVSE append clamp fallback (only when desire None) | `energy.py:5662-5667` | hold floor ≥ t+1 instead of t; raise-only, 1 pt |
| `current_park_floor` (EV release floor) | `energy_battery.py:2458-2480` | park floor t+1; 1 pt more conservative |
| KV persist / restore | `energy.py:2116`, `2416`, `2064-2065` | restores t+1; INV-R4 loop proof still holds |
| attain bypass fallback | `energy_battery.py:5316` | now third in the base chain (D1.4) |
| blind de-escalation | `energy_battery.py:6147` | blind path; unchanged |
| status attrs | `energy_battery.py:7874-7902` | display |

### 4.4 `sensor.iq_gateway_hacs_system_profile_status` attrs
- Producer `enphase_ev` `sensor.py:4085-4121`. One live reading shows `pending` stuck after apply. No URA consumer; this cycle adds none (D6 parked; drop-key use rejected in 1.4).

### 4.5 New stamps (rev 2)
- **Stamp position (rev 2.1, RG-M1, binding):** both stamps are written at the **top** of `_record_reserve_dispatch`, immediately after `value_i` is computed and **before** both early returns — the change gate `return  # SKIPPED_ALREADY_CORRECT` (`energy.py:9742-9749`) and `db is None → return` (9755-9760) — inside their own `try`. Appending them at the end would silence rules G and L in every DB-less test and on every change-gated steady re-send (incl. the CM DEFERRED row). Test `test_attempt_stamp_written_without_database_and_when_row_gated`.
- **`_reserve_last_attempt_value/_at`** — producer: `_record_reserve_dispatch` (`energy.py:9651`), every status (APPLIED, FAILED, DEFERRED), all four dispatch points. Consumer: D1 rule G only. RAM-only (restart = None = no gating; at worst one extra send after restart, C13).
- **`_reserve_last_ok_value/_at`** — producer: `_record_reserve_dispatch` when status is APPLIED (timer tap, `force_redispatch` success row). Not stamped on FAILED (raise) or DEFERRED (CM path, outcome unseen). Consumers: D1 rule L, D2 trigger. RAM-only (restart = None = rule L silent until the first landed dispatch; pre-cycle behaviour, INV-R3).
- Both live on `BatteryStrategy` (like the ledger), written from the coordinator through `self._battery`, guarded by the same `battery is not None` pattern as 9874.

---

## 5. Deliverables

### D0: Measurement probe (section 3). Read-only. Gates D1-D5.
- **Verify:** section 13 holds P1-P5 tables with the queries used.
- **Test:** none (offline script; path cited in section 13).
- **Live:** n/a.

### D1: Reserve reference = trusted witness, else cloud; landed-request term; re-send gap; attain base = intent

#### D1.1 Trust rule — one owner
`WriteVerifier.trusted_local_reserve(battery, target, soc) -> tuple[float | None, str]` returns `(value, source)` with source in `"local"`, `"stream"`, or an untrusted reason (`"disabled"`, `"unresolved"`, `"fallback_only"`, `"unavailable"`, `"low_soc_guard"`, `"soc_unknown_high"`, `"no_verifier"`). Value is non-None iff trusted. Trusted iff ALL hold:
1. `RESERVE_LOCAL_WITNESS_ENABLED` is True.
2. **rev 2.2 (D0 P5 NO-GO):** the witness is `_envoy_reserve_sensor_eid(battery)` only (never the `_local_entity_for` Enpower fallback); no tier 2, no `_resolve_reserve_witness`, source is always `"local"`. Rev 2.1 text, superseded: Witness tier resolved via `_resolve_reserve_witness(battery)`: tier 1 = `_envoy_reserve_sensor_eid(battery)` (never the `_local_entity_for` Enpower fallback); tier 2 = the stream witness, only if tier 1 is unresolved or not numeric and `RESERVE_STREAM_WITNESS_ENABLED`. **Stream resolver (rev 2.1, BUILD — no prior code; A4 was never built):** `er.async_get(hass).async_get_entity_id("sensor", "mqtt", RESERVE_STREAM_UNIQUE_ID)` with module constant `RESERVE_STREAM_UNIQUE_ID = "envoy_stream_backup_reserve"` (rung 1; the entity is the MQTT YAML sensor at `/config/packages/envoy_mqtt.yaml:97-104`, platform `mqtt`, no serial in its unique_id, so the serial-anchored `_envoy_reserve_sensor_eid` pattern cannot be reused). Reject (→ tier unresolved) when the registry entry is missing or `disabled_by` is set, mirroring `energy_write_verify.py` 467-471. Never hard-code the entity_id. **Operator precondition:** `expire_after: 60` on that sensor in `/config/packages/envoy_mqtt.yaml`, so a dead stream goes `unavailable` instead of holding a frozen value; URA cannot see this setting, so it is stated in the README and in the `RESERVE_STREAM_WITNESS_ENABLED` knob comment. **Residual (LOW, RG-L2, tracked on the card text, not a new card):** the resolver has no Envoy-serial binding; acceptable for a single install, must be bound to a serial before multi-home rollout. Tests: `test_stream_resolver_by_mqtt_unique_id`, `test_stream_resolver_rejects_disabled_entry`.
3. State numeric.
4. **Low-SOC ratchet guard (bounded both sides, R2-M1):** untrusted iff `soc is not None and soc <= target + RESERVE_LOCAL_LOW_SOC_MARGIN_PCT and target < local <= soc + RESERVE_LOCAL_RATCHET_SPAN_PCT`. A local reading far above SOC (e.g. 98 at SOC 11) is a stuck reserve, not a ratchet, and stays trusted.
5. If `soc is None`: trusted only when `local <= target`.
- `BatteryStrategy` reaches it via `self._write_verifier` (7037); `None` → `(None, "no_verifier")`.

#### D1.2 Where it runs
Only inside `_reserve_action`, after the target is final (post fold/clamp), and only when `compare_to is None`. The `compare_to` path (blind, attain-bypass no-witness fallback) is unchanged. The attain-bypass site does **not** call the trust rule (R2-H4 / R1-M2: circularity removed).

#### D1.3 Decision (evaluated in this order; first match wins)
0. **Stand-down skip** (7039-7056): unchanged, first.
1. Compute `local, src = trusted_local_reserve(...)`, `cloud = _get_state_float(write leg)`, `db = RESERVE_DISPATCH_DEADBAND_PCT`.
2. **Rule C (cloud term, pre-cycle):** if `local is None`: send iff `cloud is None or |cloud − target| ≥ db`. No gap gating (INV-R3 byte-identity). `reserve_reference_source = "cloud"` (or the untrusted reason when it is `low_soc_guard`: `"cloud_low_soc_guard"`).
3. **Rule T (trusted term):** if `local is not None`: candidate send iff `|local − target| ≥ db`. If `|local − target| < db`, the cloud term is ignored (episode-B churn suppressed). Source `"local"`/`"stream"`.
4. **Rule L (landed-request term, additive, `RESERVE_LEDGER_SEND_ENABLED`):** candidate send iff `_reserve_last_ok_value is not None and |_reserve_last_ok_value − target| ≥ db and _reserve_last_ok_value ≠ _nudge_value(target)`. Precedence (R1-M1): rule L **overrides** rule T's "within deadband = no send" (a release whose last landed request is far from target is resent even if local already shows target; cost: one redundant write), but rule L never overrides the stand-down skip or rule G. Source `"ledger"` when rule L alone causes the send.
5. **Rule G (re-send gap, R1-H2 / R2-M3):** a candidate from rule T or rule L is suppressed iff `_reserve_last_attempt_at is not None and now − _reserve_last_attempt_at < RESERVE_RESEND_MIN_GAP_S and _reserve_last_attempt_value ∈ {target, _nudge_value(target)}` (i.e. the same desire was already dispatched, by any writer, within the gap). A **different** value is never gated (a genuine desire change goes out immediately; if it collides with the Enphase 600 s window, D5 defers it). Rule G never gates a rule C send. **Raise exemption (rev 2.1, RG-H1):** rule G never gates a **raise**, i.e. a candidate with `target >= local + RESERVE_DISPATCH_DEADBAND_PCT` (rev 2.2: `>=`, so a raise of exactly the deadband is never gated — INV-R3 raise timing) when a witness is trusted, or, for a rule-L candidate with no trusted witness, `target > _reserve_last_ok_value`. A failed (raised) or silently dropped floor raise is therefore retried on the next tick, as pre-cycle code did (≤ 12/h, inside the churn cap; D5 stops the pages). The weaker "gate only when the last attempt was not FAILED" was rejected: it does not cover a silently dropped raise. Source `"in_flight"` on suppression (exposed, no action). `RESERVE_RESEND_MIN_GAP_S <= 0` disables rule G.
6. If a send survives, pass it to D2 to pick the emitted value.

`reserve_reference_source` is exposed on `sensor.ura_energy_coordinator_battery_strategy` and carried into the governor row reason.

**EVSE hold active (R1-H3, stated explicitly):** with a hold at 98 and strategy target 10, rule T sees local 98 vs 10 and emits 10; `_apply_evse_battery_hold` rewrites it in place to 98 (`energy.py:5615`). Pre-cycle, the cloud read 98, `_reserve_action` emitted nothing, and the overlay appended 98. In both cases exactly one reserve action with value 98 is dispatched. Required test `test_hold_active_local_primary_dispatches_same_value` asserts the dispatched (service, value) list is identical; the decision `reason` text may differ.

**CoordinatorManager path (R1-M4):** **live** — `_evaluate_battery` (`energy.py:7375`) runs on every TOU transition (1472) unless observation mode (1464-1470), calls `determine_mode` → `_reserve_action`, so D1/D2 apply identically there. Its row at 7450 is DEFERRED, so it stamps the attempt stamp (rule G sees it) but **not** the landed stamp and not the commanded ledger (pre-existing). Consequence: after a CM-path send, the next timer tick may resend once after the gap via rule L (bounded, one write per TOU transition). Test `test_cm_path_emits_nudge_and_stamps_attempt_only`.

#### D1.4 Attain-floor bypass base = URA intent (R2-H3, R1 table 4.2 row 2)
At `energy_battery.py:5302-5322`: `_base = _last_reserve_level_desired` if not None, else `_last_reserve_level`, else `_hw` (cloud). `_level = max(_floor, _base)`.

**Ratchet and stale-desire semantics (rev 2.1, RG-M2, DECIDED).** `_reserve_action` stamps `_last_reserve_level_desired = max(reserve_level, floor)` on every call (`energy_battery.py:7017`), including the bypass call, so inside ATTAIN `base_N = level_{N-1}`: the bypass is a ratchet seeded by the last pre-ATTAIN desire. Taken literally, a pre-ATTAIN desire that **never landed** (e.g. arbitrage CHARGE 80, write dropped or failed, local 10) would be re-asserted on ATTAIN entry (floor 50 → level 80 → grid charge to 80), which pre-cycle code did not do (base = hw 10 → level 50). **Decision: do not re-assert an unlanded raise.** The desire is used as base only if it is ≤ the active floor, or it landed (`_reserve_last_ok_value is not None and |_reserve_last_ok_value − desire| < RESERVE_DISPATCH_DEADBAND_PCT`). Otherwise the base is the floor. Reasoning: (1) the level is still `max(floor, base)`, so it never goes below the active floor in any branch; (2) an unlanded charge desire belongs to the strategy that was active before ATTAIN; the current strategy (ATTAIN) wants the floor, and nothing current wants 80, so re-asserting it is a cost-relevant raise no strategy owns; (3) the landed in-flight charge case (desire 80, landed, local 80, cloud stale 10) keeps 80, which is the R2-H3/in-flight fix this deliverable exists for; (4) the post-hold-release case (desire 10 ≤ floor 50, ledger 98) still lowers to 50, so R2-H3 holds. Floor drop inside ATTAIN (floor 80 → 20 with level 80 landed) keeps 80, same as pre-cycle (the ratchet only stops a lowering the pre-cycle bypass also did not make). Tests: `test_attain_base_does_not_reassert_unlanded_prior_desire` (desire 80 unlanded, local 10, floor 50 → level 50), `test_attain_base_keeps_landed_prior_desire` (= the existing in-flight test), `test_attain_floor_drop_keeps_level`. Mutation anchor: drop the landed check → the unlanded test RED. Call `_reserve_action(_level, compare_to=None)` when a witness or the cloud is readable (D1.3 decides the deadband against local), else `compare_to=_base` (unchanged no-witness branch, so nothing re-sends per tick). The desire stamp is chosen first (not the ledger, as review 2 suggested) because the ledger is post-overlay: right after an EVSE hold release it still reads the hold value (98), which would re-create the exact R2-H3 stuck loop. Kill switch `RESERVE_ATTAIN_BASE_INTENT_ENABLED` (False = pre-cycle `_hw`-first order). INV-R1 wording now states target is never derived from an enforced reading.

#### Acceptance criteria
- **Verify:** cloud 10 (stale), local 98, target 10, SOC 98, no prior attempt → an action (incident shape). Pre-cycle: none.
- **Verify:** cloud 98 (stale), local 10, target 10, last_ok 10 → no action. Pre-cycle sends.
- **Verify:** local unavailable, stream unavailable, cloud 10, last_ok 98, target 10, no attempt in gap → action, `source="ledger"`.
- **Verify:** SOC 6, target 10, local 16, cloud 10 → no action, `source="cloud_low_soc_guard"`.
- **Verify (R2-M1):** SOC 11, target 10, local 98, cloud 10, last_ok 10 → action (98 > 11 + 20, trusted).
- **Verify (R2-H3):** EVSE hold just released, desire stamp 10, ledger 98, local 98, cloud 10, ATTAIN, floor 50 → action lowering to 50 (or its nudge). Pre-cycle also sends 50; the rev-1 `_hw`-swap would have sent nothing.
- **Verify:** attain bypass, desire 80 (in-flight charge), cloud stale 10, local 80, floor 50 → no lowering write. Pre-cycle sends 50.
- **Verify (R1-M1):** trusted local 10 = target, last_ok 98 → action (rule L overrides rule T).
- **Verify (R1-H2):** target 10 sent at T (attempt stamp 10 @T), local still 98 at T+300 → no action, `source="in_flight"`; at T+900 → action (nudge, per D2).
- **Verify:** witness via Enpower fallback only → untrusted, `source="cloud"`.
- **Verify:** `_write_verifier is None` → untrusted, pre-cycle output.
- **Verify (synthetic pending episode, R1-H2/R2-M3):** local stuck at 98 for 70 min, every send drops or raises `control_change_pending` → ≤ 5 reserve dispatches from new paths in 70 min, none closer than 900 s for the same value.
- ~~**Verify:** stream tier used only when native unavailable (and `RESERVE_STREAM_WITNESS_ENABLED`).~~ rev 2.2 (D0 P5 NO-GO): dropped.
- **Test:**
  - `test_reserve_reference_local_primary_releases_stuck_hold`
  - `test_reserve_reference_suppresses_stale_cloud_churn`
  - `test_reserve_reference_ledger_term_when_local_unavailable`
  - `test_reserve_reference_low_soc_ratchet_guard`
  - `test_reserve_reference_low_soc_guard_upper_bound_stuck_high`
  - `test_reserve_reference_soc_unknown_high_local_untrusted`
  - `test_reserve_reference_untrusted_fallback_witness`
  - `test_reserve_reference_no_verifier_untrusted`
  - `test_reserve_reference_ledger_overrides_trusted_within_deadband`
  - `test_reserve_reference_no_resend_inside_spacing`
  - `test_resend_gap_never_gates_cloud_term`
  - `test_pending_episode_bounded_writes`
  - ~~`test_stream_witness_tier2_only_when_native_down`~~ rev 2.2 (D0 P5 NO-GO): dropped
  - `test_attain_floor_bypass_does_not_lower_inflight_with_stale_cloud`
  - `test_attain_bypass_after_hold_release_lowers_to_floor`
  - `test_hold_active_local_primary_dispatches_same_value`
  - `test_cm_path_emits_nudge_and_stamps_attempt_only` (rev 2.1, RG-M3: must use a **change-gated key**, i.e. the CM DEFERRED row hits `SKIPPED_ALREADY_CORRECT`, and still assert the attempt stamp is written)
  - `test_resend_gap_never_gates_raise` (rev 2.1, RG-H1 / C21)
  - `test_attempt_stamp_written_without_database_and_when_row_gated` (rev 2.1, RG-M1)
  - `test_attain_base_does_not_reassert_unlanded_prior_desire`, `test_attain_floor_drop_keeps_level` (rev 2.1, RG-M2)
  - ~~`test_stream_resolver_by_mqtt_unique_id`, `test_stream_resolver_rejects_disabled_entry` (rev 2.1)~~ rev 2.2 (D0 P5 NO-GO): dropped
  - `test_reserve_reference_kill_switch_byte_identical` (all four switches off → golden `test_ec_stage_a_noop_golden.py` output)
- **Mutation anchors (framing C):** always-cloud → tests 1-2 RED; delete rule L → test 3 RED; delete low-SOC guard → test 4 RED; delete the upper bound → test 5 RED; delete rule G → `no_resend_inside_spacing` and `pending_episode_bounded_writes` RED; let rule G gate rule C → `resend_gap_never_gates_cloud_term` RED; revert D1.4 base order → both attain tests RED; remove the attempt-stamp line in `_record_reserve_dispatch` → `pending_episode_bounded_writes` RED; (rev 2.1) drop the raise exemption in rule G → `test_resend_gap_never_gates_raise` RED; move the stamps after the change gate / no-DB return → `test_attempt_stamp_written_without_database_and_when_row_gated` and `test_cm_path_emits_nudge_and_stamps_attempt_only` RED; drop the landed check in the D1.4 base → `test_attain_base_does_not_reassert_unlanded_prior_desire` RED.
- **Live:** strategy attribute `reserve_reference_source` reads `local` on a normal day. Primary: at the next EVSE-hold release, a `reserve_write` row for the release value (or desire+1) within 10 min of `evse_battery_hold` going false, and local reaches desire within 2400 s. **Fallback (R1-L3)** if no hold release occurs in the validation window: any desire change of ≥ 2 while local is trusted produces a `reserve_write` row within one tick with `reserve_reference_source=local`, and no second row for the same value within 900 s. Discriminator: under the bug there is no release row and local stays at the hold value.

### D2: Same-value-drop bypass (nudge)

**Trigger (R2-H1, keyed on URA's own history, field-agnostic):** when D1 decides to send `target`, emit `_nudge_value(target)` instead iff `RESERVE_SAME_VALUE_NUDGE_ENABLED` and either
- (a) `|cloud − target| < RESERVE_SAME_VALUE_TOLERANCE_PCT` (cloud state already shows target, so the integration will likely drop it), or
- (b) `_reserve_last_ok_value is not None and |_reserve_last_ok_value − target| < RESERVE_SAME_VALUE_TOLERANCE_PCT` — the same value already left HA without raising, and local still disagrees (otherwise D1 would not be sending). This covers the case review 2 found, where the cloud state is the begin-snapshot but the drop key equals target.

`_nudge_value(t) = t + RESERVE_SAME_VALUE_NUDGE_STEP_PCT` if `t < 100`, else `t − step`. Desire stamp stays `target`; the emitted action value is the nudge.

- **Sites (2):** `_reserve_action` (sighted path, which also serves the CM path) and `force_redispatch` (~7569-7580). Both call the same pure helper; neither adds a `"number.set_value"` literal, so `RESERVE_SET_VALUE_WRITERS` and the AST lint are unchanged.
- **`force_redispatch` sinks (R2-M2):** when it nudges, the nudged value is used in **all four** sinks: the service-call `value`, the step-5 ledger stamp (7632-7634), both governor rows (7613, 7647), and the `record_dispatch_failed` value (~7596). The landed/attempt stamps then follow from `_record_reserve_dispatch`.
- **EVSE overlay append not routed:** a hold raises to captured SOC, above a stale-low cloud. If a hold value happens to equal a stale cloud, the overlay's append is the pre-cycle behaviour; once the hold releases, D1 owns the reserve again. Reviewer D must try to break this.
- **Residual (bounded, stated):** if the nudge value itself is dropped (selected already equals t+1), the next post-gap send nudges t+1 again and is dropped again: at most 4/h (INV-R4), the self-heal starvation detector stays live for it (L4: D3 only suppresses that detector while local confirms, which it does not here), and D4 pages at its threshold.

#### Acceptance criteria
- **Verify:** cloud 10, local 98, target 10 → `set_value 11`; next tick (local 11) → no action.
- **Verify (R2-H1):** cloud state 50 (begin snapshot), last_ok 10, local 50 trusted, target 10, gap elapsed → `set_value 11`, not 10.
- **Verify:** target 100, cloud 100, local 60 → `set_value 99`.
- **Verify:** `force_redispatch` with cloud = live_desire → service value, ledger, both rows and failure record all carry the nudge.
- **Verify:** cloud 15, target 10, no last_ok → `set_value 10`.
- **Verify:** `RESERVE_SET_VALUE_WRITERS` unchanged; `test_reserve_write_chokepoint_lint.py` green with no allowlist edit.
- **Test:**
  - `test_nudge_when_cloud_equals_target`
  - `test_nudge_when_landed_equals_target_and_cloud_differs`
  - `test_nudge_stable_next_tick`
  - `test_nudge_target_100_downward`
  - `test_force_redispatch_nudges_same_value_all_sinks`
  - `test_no_nudge_when_cloud_differs`
  - existing `test_reserve_write_chokepoint_lint` (unchanged)
- **Mutation:** remove the helper call in each of the 2 sites (each turns a named test RED); delete trigger (b) → `landed_equals_target` RED.
- **Live:** in the next stale-equal release, the `reserve_write` row value is desire+1 and local goes to desire+1. Without the bypass, the row is desire and local does not move (the 10-23 signature).

### D3: Verifier classifies "local confirms, cloud stale" (no false CRITICAL)

`WriteVerifier._local_confirms(battery, commanded) -> bool` = `trusted_local_reserve(battery, target=commanded, soc)` returns a value AND `|local − commanded| < RESERVE_DISPATCH_DEADBAND_PCT` (**strict**, R2-M4; deliberately not `_compare`'s `<= 2.0`). Called at three reserve-surface sites, before any anomaly or NM:

| Site | Order vs existing gates | With D3 | Latch (separate per site, keyed on effective desire, R2-L2 / R1-M6) |
|---|---|---|---|
| `_check` MISMATCH (769-789) | after the existing supersession check | `STATUS_CLOUD_STALE`; one `reserve_cloud_oracle_stale` anomaly; no NM; counters reset as for OK | `_cloud_stale_check_latch[desire]`; clears when cloud matches commanded or the effective desire changes |
| `schedule` self-heal starvation (586-621) | before the starvation emit | suppressed (no anomaly, no NM) while local confirms | none needed (suppression only) |
| `_sweep_surface` REVERTED (989-1044) | **after** the existing `is_pending_episode_active` suppression (1007-1021) and the B-MED-2 coalesce (995-1006), i.e. pending suppression still wins (R1-M7) | `STATUS_CLOUD_STALE`, one anomaly, no NM | `_cloud_stale_sweep_latch[desire]`, separate from the B-MED-2 REVERTED latch; same clear rule |

- `STATUS_CLOUD_STALE` never opens, closes, or ages a pending episode (R1-M7).
- `STATUS_CLOUD_STALE` is not `STATUS_OK`, so `is_reserve_verifiable` returns False as for MISMATCH (N3).
- CFG and storage_mode unchanged.
- Kill switch: shared `RESERVE_LOCAL_WITNESS_ENABLED`.
- At exactly |local − commanded| = 2 the existing CRITICAL path runs (no masking of the D1 boundary).

#### Acceptance criteria
- **Verify:** commanded 15, cloud 10, local 15 (trusted) at t+900 → CLOUD_STALE, one anomaly, no NM. Local 10 → existing CRITICAL (discriminator).
- **Verify:** local 17 (delta exactly 2) → existing CRITICAL.
- **Verify:** local unavailable → existing CRITICAL (INV-R3).
- **Verify:** sweep with commanded 15, cloud 10, local 15, desire 15 → no `write_reverted`; with a pending episode active → existing suppression, no CLOUD_STALE row, episode state untouched.
- **Verify:** alternating nudge/plain schedules (11, 10, 11) under one desire → one anomaly total.
- **Verify:** three same-value self-heals with local matching → no starvation NM; with local not matching → existing NM.
- **Verify:** `is_reserve_verifiable()` False for a CLOUD_STALE record.
- **Test:**
  - `test_check_cloud_stale_local_confirms_no_critical`
  - `test_check_mismatch_local_disagrees_still_critical`
  - `test_check_local_confirms_boundary_at_deadband`
  - `test_check_local_unavailable_falls_back_critical`
  - `test_sweep_cloud_stale_no_reverted_nm`
  - `test_sweep_pending_suppression_precedes_cloud_stale`
  - `test_cloud_stale_latch_keyed_on_desire`
  - `test_self_heal_starvation_suppressed_when_local_confirms`
  - `test_reserve_verifiable_false_on_cloud_stale`
- **Mutation:** remove `_local_confirms` at each of 3 sites (each a named test RED); change `<` to `<=` → boundary test RED.
- **Live:** zero "Envoy write not applied/reverted/self-heal loop: reserve_soc" `notification_log` rows while |local − commanded| < 2; `reserve_cloud_oracle_stale` rows during the next stale-cloud episode. Pre-deploy snapshot: those NM counts for 10-16..deploy.

### D4: Enforced-vs-desired dwell trip-wire (code, not soak)

In the decision-cycle tail (beside `reversion_sweep`), track how long the trusted witness has been ≥ `RESERVE_DISPATCH_DEADBAND_PCT` from the **effective desire** `_effective_reserve_desired(battery)` (R1-H3; so an active EVSE hold or DP floor is part of the desire, not a divergence). Excluded ticks (dwell resets to 0): stand-down on the effective desire, observation mode, untrusted witness (including low-SOC guard), effective desire None. Dwell start uses `dt_util.utcnow()` and is RAM-only; a restart resets it (accepted, R2-L1).

When dwell exceeds `RESERVE_ENFORCED_DIVERGENCE_TRIPWIRE_S` (default **2700** = `RESERVE_CONVERGENCE_BOUND_S` 2400 + one tick, so it fires only past the INV-R1 bound), emit one `reserve_enforced_divergence` anomaly and one NM at **HIGH**, NM latched once per day. Payload: local, source tier, cloud, effective desire, pre-overlay desire, ledger, last_ok, last attempt, `reserve_reference_source`, last `reserve_write` row id. Expose `reserve_enforced_divergence_s`. `<= 0` disables.

#### Acceptance criteria
- **Verify:** local 98, effective desire 10 for 46 min with every dispatch failing → one anomaly + one HIGH NM; at 44 min none; a second episode the same day → anomaly, no NM.
- **Verify (R1-H3 / C16):** EVSE hold active at 98, strategy desire 10, local 98 for 2 h → no dwell.
- **Verify:** low-SOC guard ticks never accumulate dwell.
- **Test:**
  - `test_enforced_divergence_fires_after_dwell`
  - `test_enforced_divergence_daily_latch`
  - `test_enforced_divergence_ignores_low_soc_and_standdown`
  - `test_enforced_divergence_uses_effective_desire_under_evse_hold`
  - `test_enforced_divergence_kill_switch`
- **Live:** `reserve_enforced_divergence_s` reads 0 or under 600 in steady state; 0 during an EV charge session with a hold. Discriminator: D0-P2 must show it **would** have fired in episodes C and D under pre-cycle code.

### D5: `control_change_pending` is DEFERRED, not a failure

In `record_dispatch_failed` (`energy_write_verify.py:1286`), when `translation_key == "control_change_pending"`: one coalesced `battery_write_deferred` anomaly per surface per episode (episode = until the next successful dispatch on that surface), no HIGH NM, governor row `WriteStatus.DEFERRED`. Surface-agnostic (all three surfaces).

**Retry semantics (rev 2, corrected):** the timer tap still stamps the commanded ledger on the raised call (4.3 decision), so the ledger does not drive the retry. The retry comes from the **landed-request stamp**, which is not advanced on a raise: on the next eligible tick (after rule G's gap), rule T (if trusted) or rule L re-sends. With no trusted witness and no prior landed request far from target, a raised send whose cloud term is also satisfied is **not** retried — that is the C4 residual (section 6), now explicitly reachable via a raise as well as via a silent drop. The CM path does not reach `record_dispatch_failed` (outcome unseen), so D5 does not apply there.

#### Acceptance criteria
- **Verify:** a raised `ServiceValidationError(translation_key="control_change_pending")` → no NM, a DEFERRED row, one anomaly for two consecutive raises.
- **Verify:** `out_of_range` still pages HIGH (discriminator).
- **Verify:** after a raised dispatch the landed stamp is unchanged, the attempt stamp advances, and the commanded ledger advances exactly as today.
- **Verify:** the next tick after the gap re-sends (trusted local disagreeing).
- **Test:**
  - `test_control_change_pending_is_deferred_not_paged`
  - `test_out_of_range_still_pages`
  - `test_raised_dispatch_does_not_advance_landed_stamp`
  - `test_tap_still_stamps_commanded_ledger_on_raise` (pins existing behaviour)
  - `test_raised_dispatch_retried_after_gap`
- **Mutation:** stamp landed on FAILED → `does_not_advance_landed_stamp` and `retried_after_gap` RED.
- **Live:** the next `control_change_pending` raise appears as `battery_write_deferred` with no `notification_log` row.

### D6 (PARKED): poll `pending` attribute / back off during an Enphase pending episode
- **Revival trigger:** D0-P3 shows `pending` clears within 5 min of local apply in ≥ 95% of cases AND a post-ship episode shows repeated pages D3/D5 did not absorb.
- **Why parked:** `pending` observed stuck after apply; rule G now bounds redundant writes to 4/h.

---

## 6. Config-extreme and combinatorial cases (each a required test; Reviewer D extends)

| # | Situation | Expected | Covered by |
|---|---|---|---|
| C1 | Local and stream unavailable, cloud fresh | Pre-cycle behaviour plus rule L | D1 test 3, kill-switch golden |
| C2 | Local trusted, cloud stale-equal to target, gateway elsewhere | Send (nudge, trigger a), converge ≤ 2400 s | D1 test 1, D2 |
| C3 | Local trusted = target, cloud stale-different, last_ok = target | No send, no CRITICAL, CLOUD_STALE | D1 test 2, D3 |
| C4 | **Both bad** (rev 2.2: stream tier not built, so this is the full native-down share — Q3 residual, stated in the README): no trusted witness (native and stream down), cloud stale-equal to target, last_ok = target or None | **Undetectable** (no witness, cloud agrees, URA believes it landed). Reachable via a pre-cycle silent drop **or** a raise when the cloud term is satisfied. Accepted residual unless D0-P5 enables the stream tier (which shrinks it to native-and-stream-down, ~0.4-1.35% of native-down time in the one measured window). README + Q3 | D1, D2 |
| C4b | No trusted witness, cloud stale-equal, last_ok ≠ target | Rule L sends (after gap), D2 nudges via trigger a | D1 test 3, D2 |
| C5 | SOC 4-9, commanded 10, local 10-26 | Guard: cloud reference, no extra writes, no D4 dwell | D1 test 4, D4 test 3 |
| C5b | SOC 11, target 10, local 98 (stuck), cloud 10, last_ok 10 | Trusted (above ratchet span) → send/nudge | D1 upper-bound test |
| C6 | SOC unknown, local > target | Untrusted, cloud reference | D1 SOC-unknown test |
| C7 | Cloud equals target, local trusted = target+1 | No send (diff 1) | D2 stable test |
| C8 | EVSE hold active 98 + inclement partial_hold 50 + arbitrage WAIT | Overlay produces 98 (unchanged dispatch). On release: target = max(strategy, floor) = 50; D1 sends 50 against local 98; nudge only if trigger a/b | D1 + `test_hold_release_with_inclement_floor_local_primary` |
| C9 | Full hold 100, cloud stale 100, gateway 60 | Nudge 99, rests at 99. Accepted exception to INV-1 (Q2) | D2 target-100 test |
| C10 | Stand-down pinned on target | Skip unchanged; D4 excluded | D1 + D4 test 3 |
| C11 | `control_change_pending` raise on nudge or release | D5 deferred, no page; landed stamp not advanced; retried after rule G gap by rule T or rule L. With no trusted witness and cloud satisfied → C4 | D5 retry test |
| C12 | Observation mode | No sends (existing dispatch gate; CM path returns before `_evaluate_battery`, 1464-1470); D4 excluded | `test_observation_mode_no_reference_sends` |
| C13 | Restart mid-episode | Ledger KV-restored; new stamps RAM-only → None (rule G ungated once: at most one extra send; rule L silent until first landed dispatch); D3/D4 latches and dwell reset | B-framing review; `test_restart_new_stamps_none_bounded` |
| C14 | Witness resolves only via the Enpower fallback | Untrusted (`fallback_only`) | D1 fallback test |
| C15 | Operator sets reserve X in the Enphase app | Local = X ≠ desire → D1 sends desire (overrides sooner than pre-cycle when the cloud did not reflect X). Same doctrine as today | README note |
| **C16** (rev 2) | EVSE hold active / DP TRANSITIONED, local = hold value, strategy desire lower | Dispatch identical to pre-cycle (one action, value = hold); no D4 dwell | `test_hold_active_local_primary_dispatches_same_value`, D4 EVSE test |
| **C17** (rev 2) | Normal change, apply lag 300-900 s | One send; at T+300 rule G suppresses (`in_flight`); local converges before T+900 → no second send | `no_resend_inside_spacing` |
| **C18** (rev 2) | Silent drop with cloud state ≠ target (begin snapshot), local trusted ≠ target | First send plain, dropped; after gap trigger b → nudge | D2 landed-equals-target test |
| **C19** (rev 2) | Desire changes inside the 600 s Enphase window | New value not gated by rule G; may raise → D5 defers; retried after gap | D5 retry test |
| **C20** (rev 2) | Delta exactly 2 between local and commanded | D1 sends (≥ 2); D3 does NOT suppress the page | D3 boundary test |
| **C21** (rev 2.1, RG-H1) | Inclement partial_hold raises target 10 → 50; local trusted 10, cloud 10, SOC 60; send of 50 raises at T (timeout or `control_change_pending`); variant: raise silently dropped (`_battery_pending_reserve` stuck 50) | Re-sent at T+300 (not `in_flight`); dropped variant nudges 51 at T+300; never later than pre-cycle | `test_resend_gap_never_gates_raise` |

---

## 7. Knobs (every new number; all rung 1)

| Name | Default | Rung | Why | Kill semantics |
|---|---|---|---|---|
| `RESERVE_DISPATCH_DEADBAND_PCT` | 2 | 1 | Existing literal (7059), named; operator "keep ±2" ruling; shared by D1/D3/D4 | none (change = review) |
| `RESERVE_LOCAL_WITNESS_ENABLED` | True | 1 | Trust-hierarchy change; backout-knob precedent | False = rule T, stream tier and D3 off |
| ~~`RESERVE_STREAM_WITNESS_ENABLED`~~ rev 2.2 (D0 P5 NO-GO): not built | set by D0-P5 (True on GO, False on NO-GO) | 1 | Second trust input, measured once. Precondition (comment on the constant): `expire_after: 60` on the stream sensor in `/config/packages/envoy_mqtt.yaml` | False = native tier only |
| ~~`RESERVE_STREAM_UNIQUE_ID`~~ rev 2.2 (D0 P5 NO-GO): not built | `"envoy_stream_backup_reserve"` | 1 | Registry key for the stream witness (platform `mqtt`); not a number, but named so no entity_id is hard-coded | n/a (disable via the switch above) |
| `RESERVE_LEDGER_SEND_ENABLED` | True | 1 | Additive send path (rule L) | False = rule L off |
| `RESERVE_SAME_VALUE_NUDGE_ENABLED` | True | 1 | Writes a value ≠ desire | False = plain target (drops recur) |
| `RESERVE_ATTAIN_BASE_INTENT_ENABLED` | True | 1 | Changes the attain-bypass base (pre-existing leak fix) | False = pre-cycle `_hw`-first base |
| `RESERVE_SAME_VALUE_NUDGE_STEP_PCT` | 1 | 1 | Smallest step the integration accepts as a different value; costs ~0.4 kWh | none (0 would disable the nudge; use the switch) |
| `RESERVE_SAME_VALUE_TOLERANCE_PCT` | 0.5 | 1 | Reserve is integral; < 0.5 = "same integer" | none |
| `RESERVE_LOCAL_LOW_SOC_MARGIN_PCT` | **5** (rev 2.2: D0-P1 nominal-commanded figure; the guard compares SOC to the nominal target URA sent, not the gateway's effective value) | 1 | Fitted lower edge of the ratchet regime | 0 = guard only when SOC ≤ target |
| `RESERVE_LOCAL_RATCHET_SPAN_PCT` | 20 (D0-P1) | 1 | Fitted upper edge (10-17: local ≤ 26 at SOC 4-9); above it a high local is a stuck reserve | 100 = rev-1 unbounded guard |
| `RESERVE_RESEND_MIN_GAP_S` | 900 | 1 | ≥ Enphase `CONFIRMATION_WINDOW_S` 600 (no collision with our own previous request) and ≥ measured apply-lag p90 461 s (no duplicate during normal lag); equal to `CONF_PENDING_ATTEMPT_1_AGE_S` (900, `energy_const.py:511`) so it matches the watchdog ladder spacing. Separate name because the watchdog value governs a different path; a test pins them equal | `<= 0` disables rule G |
| `RESERVE_APPLY_LAG_ALLOWANCE_S` | 900 | 1 | Bound term for INV-R1: ≥ measured p99 (D0-P4 confirms) | n/a (invariant constant) |
| `RESERVE_CONVERGENCE_BOUND_S` | derived = 2 × 300 + gap + allowance = 2400 | n/a | Invariant/test constant | n/a |
| `RESERVE_ENFORCED_DIVERGENCE_TRIPWIRE_S` | 2700 | 1 | Bound + one tick, so it fires only past INV-R1 | `<= 0` disables D4 |
| D3 / D5 episode coalesce | no time window: latches clear on events (D3: cloud matches or effective desire changes; D5: next successful dispatch) | n/a | No new number | n/a |

No options-flow or Number additions (Q1).

---

## 8. Marginal-benefit decomposition

| Piece | Captures | Marginal risk ingredient | Verdict |
|---|---|---|---|
| D1 rule T (local-primary deadband) | Releases stuck holds A-D while local is up; kills episode-B churn | New trust input. Contained by trust rule + INV-R3 | **BUILD (core)** |
| D2 nudge | Without it D1 would not have released 10-23 (`number.py:385` drop) | Writes desire+1; target-100 corner | **BUILD (core)** |
| D3 CRITICAL gate | Removes false pages | New status; guard predicate unchanged | **BUILD (core)** |
| Rule G (re-send gap) (rev 2) | Prevents duplicate sends during normal apply lag and pending episodes, and own-request collisions | One new timing comparison against an existing-path stamp; never gates rule C | **BUILD (required: without it rule T + nudge loops at 12/h)** |
| Landed + attempt stamps (rev 2) | Make retry-after-raise and the nudge trigger correct without changing the shared ledger | Two RAM stamps at one choke point | **BUILD (cheaper and safer than changing the tap)** |
| Rule L | Local-down + stale-cloud release where a landed request differs | Additive send | **BUILD** |
| D1.4 attain base = intent | Closes the pre-existing "lower in-flight charge on stale cloud" leak without the rev-1 self-perpetuating hazard | Base order change, own kill switch | **BUILD** |
| Stream tier (rev 2) | Shrinks C4 from 7.4% local-down to native-and-stream-down | Second trust input; measured once in Sept | **PARKED (rev 2.2, D0 P5 NO-GO)** |
| D4 trip-wire | No-soak code trip-wire for INV-R1 | Alert-only | **BUILD** |
| D5 deferred classification | Removes ~0.5 HIGH pages/day in pending episodes | Classification only | **BUILD** |
| Changing the tap to not stamp on raise | Same retry benefit as the landed stamp | Ripples into 9 consumers (4.3), contradicts the B2 intent-ledger doctrine | **REJECTED** (revive only if a consumer is shown to need hardware-truth semantics) |
| D6 poll `pending` | Marginal over rule G + D3 + D5 | Third oracle, wrong-looking semantics | **PARK** |
| 2-step nudge completion | 1 point of reserve | Second write inside 600 s guarantees a collision | **PARK** (revive if +1 residual costs anything, or if Q2 = "no dip") |
| Physics witness | C4 residual | Stream NO-GO 10-07 for that derivation | **PARK** (revive if D4/rule-L data show C4 occurring with the stream tier also down) |

---

## 9. Non-goals and scope moved out

- **N1.** Retire the local write-failover → sibling card `EC-WRITE-FAILOVER-RETIRE-1` (Tier 2-DB).
- **N2.** Long Envoy outage recovery → parent card phase 3.
- **N3.** `is_reserve_verifiable` semantics unchanged.
- **N4.** CFG and storage_mode surfaces: no local-primary logic.
- **N5.** Why the cloud goes stale: upstream (Q4).
- **N6.** Cloud-first writes unchanged.
- **N7.** `envoy_status` "stale" not a gate.
- **N8.** Token expiry alert stays on the parent card.
- **N9** (rev 2). Commanded-ledger semantics (`_last_reserve_level`, tap stamp-on-raise) unchanged.
- **N10** (rev 2). The CM path's unseen outcome (no ledger stamp, DEFERRED row) is a governor known limit, not fixed here; this cycle only makes it stamp the attempt stamp through the existing row.
- **N11** (rev 2). Blind de-escalation path keeps the pre-cycle cloud compare even when a witness is healthy.

---

## 10. Operator questions (recommended answer in brackets; assumed unless changed)

- **Q1.** Kill switches (now six, section 7) at rung 1 or a live Switch? [Rung 1; backout-knob precedent.]
- **Q2.** Full hold 100 with stale-equal cloud: nudge to 99 and rest, or build the 2-step completion now? [99 and rest; the gateway is below 99 in that state anyway.]
- **Q3 (revised).** C4 residual: with the stream witness, it shrinks to "native AND stream down AND cloud stale-equal AND URA believes the value landed". Accept that remainder until the physics witness exists? If D0-P5 is NO-GO, the residual is the full 7.4% local-down share of stale-cloud time, now also reachable via a `control_change_pending` raise. [Accept in both cases; README states which.]
- **Q4.** File an upstream `enphase_ev` issue (stale reserve payload; same-value early return keyed on the pending value while state shows the begin snapshot)? [Optional; operator call. Rev 2 adds the second point, which is a crisper bug report.]
- **Q5.** D4 HIGH once a day at 2700 s (was 1800 s in rev 1; raised to sit past the new INV-R1 bound)? [Yes.]

---

## 11. Tier classification and review plan

**Tier 3.** Triggers: threads a value through the shared reserve emission primitive (`_reserve_action`, attain bypass, `force_redispatch`, CM path); cost-impacting (~27 kWh mid-peak import in the incident); changes the write-verify trust hierarchy; multi-fix-up history.

Process:
- **Plan reviews:** rev 1 reviewed twice (appended). **Rev 2 re-review (one pass, completeness framing)** on the deltas: new stamps at `_record_reserve_dispatch`, rule G, D1.4 base order, stream tier resolution, D3 order vs pending suppression.
- **Build:** `ura-super-builder`, worktree under `.claude/worktrees/`.
- **Build reviews (4):** A local correctness (trust rule, rule order, nudge trigger arithmetic, strict-vs-inclusive boundaries); B state machine / restart / byte-identity / CM path / no suppression of rule C; C real per-site source mutation (anchors in D1-D5); D falsify INV-R1..R4 across the whole reserve surface including pre-existing code, with legal-config repros (start with C4, C16, C18, C19).
- **Orchestrator:** re-greps sites (`"reserve_soc_number"`, `number.set_value`, `_reserve_action(`, `_record_reserve_dispatch`, `_last_reserve_level\b`) and re-runs one mutation before ship.
- **Operator checkpoint before deploy.**
- **Pre-deploy snapshot:** 7-day counts of reserve `write_verification_failed`, `write_reverted`, `self_heal_starvation`, `battery_write_failed`, NM rows, reserve writes per hour.

---

## 12. Plan completion tracking (to be filled at ship)
| Item | Shipped? | If not, why / where tracked |
|---|---|---|
| D0-D5 | | |
| Stream tier | | D0-P5 verdict |
| D6 | parked | D0-P3 trigger |
| N1 failover retire | moved | sibling card |
| N2 outage recovery | parked | parent card phase 3 |

## 13. D0 report

**Run 2026-10-24 10:27 CDT (15:27 UTC), read-only** (`ssh ha "sudo -n python3 -"`, both DBs opened `mode=ro`). Prober: `ura-prober`. Scripts: `scripts/probes/ec_reserve_d0/{s0,s1,s2,dump,s8}.py` (extraction), `{p1b,sim,p3}.py` (analysis). Sources: recorder `/config/home-assistant_v2.db` (`states`, `state_attributes`), URA DB `ura_activity_log action='reserve_write'` (226 rows, 10-16 23:42Z to 10-24 07:05Z), `anomaly_log`, `notification_log`.

### 13.0 Data limits (read first)
- **Recorder window is 10-17 09:12 UTC to now (7.3 days), not 10-16.** `purge_keep_days: 7` (`/config/configuration.yaml:13`). Retained local series starts 10-17 12:47Z, cloud 10-17 13:43Z. The 10-16/early 10-17 data cited in the plan (e.g. "local 10-26 at SOC 4-9") is purged; `reserve_write` rows exist from 10-16 23:42Z.
- The recorder is change-only. Series used: `sensor.envoy_482543015950_reserve_battery_level` (local, 70 states), `number.iq_battery_hacs_battery_reserve` (cloud, 74), `sensor.envoy_482543015950_battery` (SOC, 1,417), `sensor.iq_gateway_hacs_system_profile_status` (896 incl. attributes), `sensor.envoy_stream_backup_reserve` (18).
- Hold windows (EVSE hold on/off) are not logged on release (a deadbanded release writes no row). They were reconstructed from `sensor.span_panel_garage_{a,b}_evse_power` > 500 W (+4 min). Row cadence agrees with this proxy (rows stop when EV power drops). Stated as an approximation.

### 13.1 P1 low-SOC regime: **GO** (constants hold; one recommendation)
Method: 10,123 minutes with local, SOC and last-commanded value all known; "settled disagreement" = |local - commanded| >= 2 more than 600 s after the last `reserve_write` row; episodes A-D windows excluded for the bin table.

| SOC - commanded (bin) | minutes | settled |local-cmd|>=2 | max(local-cmd) | max(local-SOC) | min(local-SOC) |
|---|---|---|---|---|---|
| -4 .. -2 | 970 | 6 | 0 | 2 | -85 (episode edge) |
| 0 .. 1 | 1,370 | 6 | 5 | 5 | -2 |
| 2 .. 3 | 186 | 24 | 2 | 0 | -4 |
| 4 .. 5 | 144 | 5 | 2 | -2 | -6 |
| 6 .. 29 | 1,300+ | **0** | 0 | <= -6 | |
| >= 30 | 3,202 | **0** | 0 | | |

- Wobble (local above commanded with no new write) exists only for SOC - commanded <= 5, all on 10-17 12:58 to 13:42Z (commanded 3, local 5 to 8, SOC 3 to 7). The commanded 3 was **rejected** (`battery_write_failed`, `out_of_range`, 10-17 12:47:23 and 13:17:23, `anomaly_log`), so the gateway enforced 5; relative to the effective 5 the largest SOC - commanded in a wobble minute is **2**; relative to the nominal 3 it is **4**.
- Upper edge: the largest (local - SOC) in any wobble minute is **5**. The audit's 10-26 at SOC 4-9 (17 above SOC) is outside the retained window and **not re-verifiable**; it is still under 20.
- Gate test ("wobble with SOC above commanded + 5, or local above SOC + 30"): **not triggered** (max 4 and 5). D1.1 is not redesigned.
- Episodes C legs 2 and 3 (SOC 13, local 13, target 10) sit inside the guard at margin 3 (13 <= 10 + 3). The guard makes local untrusted there; rule L (last landed 13 vs target 10) releases them anyway (13.2). Without rule L the guard would mask them (cost about 3 points). Margin 0, 3, 5, 8 and span 20 / 30 give identical release outcomes in the replay.
- **Recommendation:** keep `RESERVE_LOCAL_LOW_SOC_MARGIN_PCT` = 3 (valid against the effective commanded value) but set it to **5** if the builder compares to the *nominal* commanded value (covers the observed 4). Keep `RESERVE_LOCAL_RATCHET_SPAN_PCT` = 20. Observation for the builder (not a D0 gate): target below 5 is rejected by the integration (`out_of_range` at 3); the nudge of a target of 4 would be rejected too.

### 13.2 P2 replay: **GO**
Method: tick-by-tick (300 s) closed-loop replay of D1 rules C/T/L/G, the nudge triggers and the INV-R1 dwell, margin 3 / span 20, over 10-17 13:00Z to now. Inputs are recorded SOC, cloud, local and the last `reserve_write` desire/value; the gateway is modelled as recorded local until a simulated send, then local = sent value after the apply lag (30 s, and 461 s as a pessimistic run), dropped silently when the value equals the last selected value; the override ends at the next recorded numeric local change. The **pre-cycle** variant (rule C only) is run on the same inputs as a validation: it reproduces **102 re-sends in episode B's window, exactly the 102 actual rows**.
**Limitations:** target = last row's `desire` carried forward (a desire change with no row is invisible); cloud is the recorded cloud (a simulated send does not change it); hold windows are the EVSE-power proxy; ticks are not aligned to the real tick phase; recorded cloud is empty before 10-17 13:43Z (see the artifact below); the pending-episode shape is not exercised (as the plan stated) and stays on the synthetic test.

| Episode | Pre-cycle (actual) | New rules (replay) | Released within 2400 s? |
|---|---|---|---|
| A, 10-19 (hold 79/98; cloud 9) | hold ended 18:31Z (EV off); local stuck 79 vs desire 10 until the next hold at 19:26Z, about 55 min | 18:47Z rule T sends 10 (plain) | **Yes**, 16 min after the EV session ended |
| B, 10-19 21:37Z to 10-20 06:07Z (cloud 98, local 10 = desire) | 102 identical re-sends, 12/h for 8 h, churn NM, 5 false CRITICAL pages | 0 re-sends (rule T ignores the cloud term) | n/a (local already = desire); churn removed |
| C, 10-22 06:10Z to 10-23 10:00Z (holds 15, 13, 13; cloud 10; local 15/13) | unreleased 27.8 h | 06:17Z rule T sends **11** (nudge, trigger a: cloud = target); 10-22 08:17Z and 10-23 08:17Z rule L sends 11 (SOC 13 inside the guard, last landed 13) | **Yes** on all three legs, 7 min after each hold ended |
| D, 10-23 19:40Z to 10-24 00:23Z (hold 98; cloud 10; local 98) | unreleased 4 h 43 min, ended by the operator write 12 | 19:47Z rule T sends **11** (nudge) | **Yes**, 7 min after the hold ended |
| E (extra, not in the plan), 10-24 00:25Z to 06:06Z (cloud stuck 12; local 10, then 15) | 66 re-sends, churn NM 01:30Z, false CRITICAL 02:15Z / 02:20Z | 00:27Z sends 10 (operator had written 12, legitimate); then 0, except 04:07-04:17Z (local unavailable, rule C = pre-cycle, 3 sends) | n/a |

- **INV-R1:** pre-cycle violates it 3 times (10-22 06:17Z, 10-22 14:32Z, 10-23 19:47Z); new rules: **0 violations** at lag 30 s and at lag 461 s. Every minute left unreleased in the new run: none.
- **D4 would have fired under pre-cycle code:** yes, in episodes C (10-22 07:07Z, 15:22Z) and D (10-23 20:37Z), as expected (NM latched once per day: 10-22 and 10-23). Under the new rule: **none**. Episode A's pre-cycle dwell is about 45 min (< 2700 s), no fire.
- **INV-R4:** pre-cycle: 195 non-hold sends, max **12/h**, 16 hours above 4. New: 18 sends (22 at lag 461): rule T 4 to 5, rule L 2, rule G suppressed 1, rule C 10 to 15. New-path (T and L) sends: **max 1 per hour**, none within 900 s of the same value. Max total in any hour is 6 (9 at lag 461), all in 10-17 13:00Z and all **rule C** with `cloud = None`: an artifact (recorded cloud history starts 13:43Z, so rule C sees "cloud unreadable" and sends every tick, which is pre-cycle behaviour, INV-R3). Excluding that hour, no hour exceeds 3 and every send is either a new-path send or a rule C send in the daily 04:06-04:20Z local-unavailable window (pre-cycle behaviour).
- **Notes for the builder:** (1) the nudge alternation 16, 16, 15 at 10-24 04:07-04:17Z shows D2 triggers apply to rule C sends too (the plan text says "when D1 decides to send"); consistent, but test it. (2) The C-leg releases depend on rule L when SOC is within margin of target, so `_reserve_last_ok_value` being None after a restart (RAM-only) means a restart inside such a window is not released until the first landed dispatch (C13 stands).
- Pre-cycle false pages in the window (D3 value): 15 distinct CRITICAL "Envoy write not applied / reverted / self-heal loop: reserve_soc" events (`notification_log`, 10-19 18:42Z to 10-24 02:20Z), **all 15 with the local sensor within 0 of the commanded value** (INV-R2 falsifier: 0 of 15 were true failures).

### 13.3 P3 pending attribute: **D6 stays PARKED**
`sensor.iq_gateway_hacs_system_profile_status` stores `pending`, `requested_reserve_percentage`, `selected_reserve_percentage`, `effective_reserve_percentage`, `pending_requested_at` in recorder attributes (pending key present in 895 of 896 states; true in 253).
- 20 `pending: true` intervals. **15 cleared in 51 to 204 s** (p50 76 s). **5 never cleared on their own: 3,981 s, 30,674 s, 99,268 s, 17,217 s, 20,185 s**, i.e. exactly episodes A, B, C, D and E; in each, local had matched the request within 8 to 46 s of `pending` turning true and `pending` stayed true for the whole stale-cloud episode.
- Share clearing within 5 min: **75%** (15 of 20) against the revival bar of 95%. Not met. `pending` stuck true is the same fault as the stale cloud, not an independent oracle. D6 remains parked.

### 13.4 P4 apply lag and write collision: **GO**
- Method: for every `reserve_write` row (applied, timer path) whose value differs from the local reading 120 s earlier, time to the first local reading within 1 of the written value. n = 21 landed rows with local data in the window (8 more rows 10-16/10-17 predate the retained local series; excluded).
- **Local apply lag (s): p50 7.8, p90 69, p99 177, max 177** (signed min -23 s: local moves before the log row, the timestamp artifact the audit noted). Slowest: 10-20 07:11Z (177 s), 10-17 13:52Z (101 s), 10-17 13:42Z (69 s).
- Named cases: operator write 12: `pending_requested_at` 00:23:40Z, local 12 at 00:23:45Z (**5 s**), cloud 12 at 00:25:09Z (89 s). URA write 10: requested 00:30:05Z, local 10 at 00:30:13Z (**8 s**), cloud **never** updated (stale 12 until 06:06Z).
- `RESERVE_RESEND_MIN_GAP_S` = 900 >= 600 (Enphase window) and >= p90 69 s: **PASS**. `RESERVE_APPLY_LAG_ALLOWANCE_S` = 900 >= p99 177 s: **PASS** (the plan's 461 s p90 came from the July B0 probe; this window is much faster, so 900 is conservative).
- `control_change_pending` raises in the window: **0**. `anomaly_log` `battery_write_failed` = 3 rows, all `out_of_range` (commanded 3, 10-17). 11 pairs of different-value writes less than 600 s apart (e.g. 10-23 09:54:59Z then 10:00:13Z; 10-24 06:10:03Z then 06:15:17Z) were all accepted, none raised. Caveat: n = 21, healthy-gateway lags only; the stuck-pending shape (07-16 67-minute case, 10-12..14) is outside the retained window, so D5's classification stays covered by the synthetic test only.

### 13.5 P5 stream witness: **NO-GO** (tier 2 ships `RESERVE_STREAM_WITNESS_ENABLED = False`, PARKED)
- The entity exists and is enabled: entity registry `sensor.envoy_stream_backup_reserve`, platform `mqtt`, unique_id `envoy_stream_backup_reserve`, `disabled_by: null` (`/config/.storage/core.entity_registry`); YAML `/config/packages/envoy_mqtt.yaml:97-104` has `expire_after: 60`.
- **It has never been numeric in the retained window.** Recorder: 18 states 10-17 18:24Z to 10-24 15:10Z, **all `unavailable`**; same for all 23 `*_stream_*` entities (18 rows each, 18 unavailable), including `binary_sensor.envoy_stream_publishing`. `core.restore_state` (last_seen 15:13Z) = `unavailable`. No agreement/lead-lag/episode A-E tracking can be computed because there is no numeric sample. (These rows are the restart/MQTT-reconnect unavailable writes; they are not excluded by the recorder config: only `*_stream_data_timestamp/_age` are, `configuration.yaml:314-315`.)
- Cause (from the board, not re-read live): the add-on `13e68335_envoy_to_mqtt_json` was **stopped and set to boot=manual 2026-10-05** after the 48 h A/B went NO-GO (peak battery cutouts 30 to 138 per 48 h with the stream running; `kanban.data.yaml` readout_2026_10_05 line 1099, disposition line 1090). `kanban.data.yaml:19960` already records `sensor.envoy_stream_grid_power` dead for 4+ days. The Sept 3.7 PASS (10/10) therefore describes a feed that is intentionally off. I could not read the add-on state live (`ha addons` returned unauthorized).
- **After today's HA restart** (unavailable rows at 15:10:18Z): the stream did **not** recover (still `unavailable` in the 15:13Z restore state), which is expected. For comparison, local `sensor.envoy_482543015950_reserve_battery_level` recovered (15 at 15:10:31Z) and the cloud number recovered (15.0 at 15:11:41Z); profile status reads `pending: false`, `selected_reserve_percentage: 15`.
- Consequence: C4 residual stands at the full local-down share (local unavailable 7.4% of the window, plus the daily 04:06-04:20Z outage). Recommend the builder **does not build the tier-2 resolver at all** (marginal-benefit rule: the enabled flag would be dead code on a retired feed); park it with revival trigger "stream add-on re-enabled AND a 3.7-style reserve-change match measured". Plan edit needed in D1.1, 1.4, 7 and the two resolver tests if so.

### 13.6 Gate summary
| Gate | Verdict | Basis |
|---|---|---|
| P1 bounds for `RESERVE_LOCAL_LOW_SOC_MARGIN_PCT` / `RESERVE_LOCAL_RATCHET_SPAN_PCT` | **GO** (3 / 20; consider 5 if nominal commanded is used) | max SOC-cmd in wobble 4 (2 effective), max local-SOC 5, redesign thresholds 5 / 30 not hit; upper edge from audit not re-verifiable |
| P2 replay (INV-R1, INV-R4, episodes A-D) | **GO** | A, C (3 legs), D released in 16, 7, 7 min; B churn 102 to 0; INV-R1 0 violations; new-path max 1/h; pre-cycle D4 would fire in C and D, new rule none |
| P4 apply lag vs `RESERVE_RESEND_MIN_GAP_S` / `RESERVE_APPLY_LAG_ALLOWANCE_S` | **GO** | p50 7.8 / p90 69 / p99 177 s (n = 21) vs 900 / 900; 0 `control_change_pending` raises |
| P5 stream witness | **NO-GO** | never numeric; add-on retired 10-05; tier 2 off and parked |
| P3 / D6 | **stays PARKED** | 75% clear within 5 min (bar 95%); the 5 that never clear are the stale-cloud episodes |
| Gate rule (P1, P2, P4 in bounds) | **Build may be dispatched** | operator checkpoint rules unchanged |

### 13.7 Build notes and deviations (rev 2.2, build + review fix-up 2026-10-24)

Branch `fix/ec-reserve-oracle-phase2`. Deviations from the rev 2.1 text, each with a mutation-anchored test in `quality/tests/test_ec_reserve_oracle_phase2.py`:

| # | Deviation | Why |
|---|---|---|
| B1 | `RESERVE_LOCAL_LOW_SOC_MARGIN_PCT` = 5 | The guard compares SOC to the nominal target URA sent (D0-P1 nominal figure 4). |
| B2 | No D2 nudge on a rule-C (no-witness) send | A nudge would change the value of a pre-cycle send, which is not one of INV-R3's two exceptions. Open for review. |
| B3 | Raise exemption uses `>=` | A raise of exactly the deadband is a rule-T candidate; INV-R3 says no raise is later than pre-cycle. |
| B4 | Blind de-escalation passes `witness_reference=False` | Code calls the blind path with `compare_to=None` when the write leg is readable; N11 requires the pre-cycle compare there. |
| B5 | D1.4 base (fix-up HIGH-1): desire kept when <= floor OR confirmed by the landed request, the write leg, or the trusted local (each within the deadband); unconfirmed → the pre-cycle hardware read, else the floor (never the ledger); no desire → hardware, then ledger | The rev 2.1 "landed only" rule lowered an in-flight 80 to the floor on tick 2 after reboot (desire adopted from hardware, landed stamp None) and after a CM DEFERRED raise. The attain site reads the trust rule as evidence only (never as the target). |
| B6 | Attain call drops `compare_to` when the write leg OR a trusted local is readable (fix-up MED-A) | Otherwise an unreadable cloud masks a stuck local. |
| B7 | Nudge-aware consumers of the commanded ledger (fix-up HIGH-2): pending-watchdog cancel-on-move, `is_standdown_active_for_value`, conduct exception (d) treat `_nudge_value(desire)` as the desire; the ledger `_at` anchor does not move on the plain/nudge pair of one desire (timer tap and `force_redispatch`) | A nudged command cancelled the ladder every tick (attempts 2-3, final page and stand-down never ran), a stand-down pinned on the nudge never skipped the target, and exception (d) exempted every tick. |
| B8 | A raise nudges at most once per `RESERVE_RESEND_MIN_GAP_S` (fix-up D-MED-1; decision-time RAM stamp `_reserve_last_nudge_at`) | A dropped raise retries every tick; without this it alternated plain/nudge every tick. One hour = 12 writes, 4 nudges. |
| B9 | D2 trigger (b'): last attempt == target and it did not raise (`_reserve_last_attempt_failed`, stamped at `_record_reserve_dispatch`; FAILED or a raised DEFERRED = failed; the CM path's unseen DEFERRED = not failed) (fix-up D-MED-2) | A CM-path first send never stamps the landed stamp, so the drop was not bypassed until ~3300 s (> INV-R1 2400). |
| B10 | `trusted_local_reserve` fails closed on an exception: `(None, "error")` | Review C T11. |
| B11 | `force_redispatch` success closes the D5 deferred episode; `reserve_reference_source` names `compare_to` / `blind_cloud` on those paths; `reserve_last_landed(_at)` exposed on the strategy sensor | Review LOWs. |
| B12 | `reserve_reference_source` goes into the `reserve_write` row payload (not the reason text); a timer DEFERRED row does not arm the change-gate memo; D4 payload carries the last attempt time instead of a row id | Golden reasons stay byte-identical; D-4 recovered re-send must log; rows are fire-and-forget. |
| B13 | Stream tier not built (D0-P5 NO-GO) | Q3 residual = full native-down share. |

**Known limits (documented, not fixed):** stamps are RAM-only (a restart inside a stuck window delays the rule-L release to the first landed dispatch); D4 dwell resets on any single untrusted tick (local unavailable, low-SOC guard), so a stuck episode spanning the daily 04:06-04:20Z local outage restarts its 2700 s clock — accepted rather than adding a new tolerance knob; targets below 5 (and their nudge) are rejected by the integration (`out_of_range`).

**Commanded-ledger consumers re-enumerated against a nudged value (fix-up HIGH-2):** `_commanded_ledger` → `_check` supersession / sweep / `_compare` (tolerance 2, benign); pending watchdog compare + cancel-on-move (fixed); stand-down value (fixed); `_conduct_check_reserve` floor (t+1, 1 pt stricter, benign) + exception (d) (fixed); EVSE append clamp fallback (desire None only, raise-only 1 pt); `current_park_floor` (1 pt more conservative); KV persist/restore (`energy.py` 2069/2121/2421, restores t+1, benign); attain-bypass ledger fallback (desire None only); blind `BLIND_RESPECT_MANUAL_LOWER` check (ruled False; t+1 > desire so cannot misfire); D4 payload and status attrs (display); timer tap / EVSE overlay / `force_redispatch` stamps (producers; `_at` pair rule added).

### Rev 2 disposition (all findings of both plan reviews)

| Finding | Resolution | Section |
|---|---|---|
| R1-H1 ≈ R2-H2 (tap stamps ledger on a raised dispatch) | Verified at `energy.py:9876-9883` (stamp before `ok` check). Tap NOT changed (ripple + B2 intent-ledger doctrine); new landed-request stamp `_reserve_last_ok_value` carries the retry; consumer table of `_last_reserve_level` (incl. `_conduct_check_reserve` 2043, EVSE clamp fallback 5662-5667, `current_park_floor`, KV) added; D5 retry claim rewritten; test renamed and an existing-behaviour pin added | 1.4, 4.3, 4.5, D5, C11, N9 |
| R1-H2 ≈ R2-M3 (re-send during apply lag / 600 s window) | Rule G: `RESERVE_RESEND_MIN_GAP_S` = 900 (≥ 600 window, ≥ 461 s p90, equals watchdog spacing), attempt stamp at the single `_record_reserve_dispatch` choke point covering all four dispatch points; never gates rule C; P2 limitation stated; synthetic `test_pending_episode_bounded_writes` | 2 (INV-R4), 3, 4.5, D1.3, C17, 7 |
| R1-H3 (INV-R1/D4 vs pre-overlay desire) | INV-R1 and D4 compare to `_effective_reserve_desired` (1787); C16; D1 behaviour under hold stated with a dispatch-identity test | 2, D1.3, D4, C16 |
| R1-H4 (stream witness prior art) | REUSE gated on new D0-P5; tier 2 in the trust rule; `RESERVE_STREAM_WITNESS_ENABLED`; Q3 revised | 1.1, 1.4, 3, 4.1a, D1.1, C4, 10 |
| R2-H1 (nudge keyed on wrong field) | Verified the field split from review's cites (not re-read on the mount: flagged). Trigger = cloud equals target OR landed request equals target; profile-sensor `selected_reserve_percentage` rejected as a third oracle; test for state ≠ target, landed = target | 1.3, 1.4, D2, C18 |
| R2-H3 (attain `_hw` swap self-perpetuating) | Base = desire stamp → ledger → `_hw` (desire first, because the ledger still holds the hold value after release; review's ledger-first suggestion would re-create the loop); repro test; INV-R1 wording "target never derived from enforced reading"; own kill switch | 2, D1.4, 7 |
| R2-H4 ≈ R1-M2 (circular `_reserve_reference`) | API split: `WriteVerifier.trusted_local_reserve` runs only inside `_reserve_action` after the fold; the attain site does not call it; `compare_to` branch unchanged | D1.1, D1.2, D1.4 |
| R1-M1 (rules 2 vs 3 contradict) | Explicit order: stand-down → C/T → L overrides T's within-deadband → G gates T/L only; test | D1.3 |
| R1-M3 (trust API does not exist) | Owner `WriteVerifier`; resolver reports tier; `_write_verifier None` = untrusted | 1.4, D1.1 |
| R1-M4 (CM path) | Verified live on TOU transitions (`energy.py:1472`, skipped in observation 1464-1470). D1/D2 apply; DEFERRED row stamps attempt only; bounded one extra rule-L send; D5 n/a; test | D1.3, D5, N10 |
| R1-M5 (governor/lint/prior plans) | Cited; acceptance "allowlist unchanged, lint green" | 1.1, D2 |
| R1-M6 (unnamed numbers, latches) | Step and tolerance named; coalesce is event-based (no number); separate latches per site with clear rules | 7, D3 |
| R1-M7 (D3 vs pending suppression) | Pending suppression and B-MED-2 coalesce first; CLOUD_STALE never touches pending episodes; test | D3 |
| R2-M1 (low-SOC guard masks stuck-high) | Upper bound `RESERVE_LOCAL_RATCHET_SPAN_PCT` (20, fitted by P1); C5b test | D1.1, 3, 7, C5b |
| R2-M2 (`force_redispatch` sinks) | All four sinks carry the nudge; test asserts each | D2 |
| R2-M4 (tolerance at exactly 2) | `_local_confirms` strict `< 2`; boundary test; C20 | D3, C20 |
| R1-L1 (blind exclusion premise) | Cited blind trigger 6091 (`not envoy_avail and soc is None`); stated the blind path keeps cloud compare by design even with a healthy witness | 4.2, N11 |
| R1-L2 (INV-R1 falsifier muddled) | Reworded on "no row dispatched within the bound" | 2 |
| R1-L3 (D1 Live depends on hold release) | Fallback live criterion on any desire change ≥ 2 | D1 Live |
| R1-L4 (self-heal starvation as backstop) | Stated: D3 suppresses it only while local confirms, so it remains the backstop for a dropped nudge | D2 residual, D3 |
| R1 enumeration gap (`command_trail` 2569-2595) | Listed as a display consumer | 4.1 |
| R2-L1 (time source, dwell restart) | `dt_util.utcnow()` everywhere; dwell RAM-only, restart resets (accepted) | 2, D4, C13 |
| R2-L2 (D3 latch reset on alternation) | Latches keyed on effective desire | D3 |
| R2-L3 (resolver must report path) | `_resolve_reserve_witness` returns (eid, tier) | 1.4, D1.1 |

### Rev 2.1 disposition (rev-2 re-review)

| Finding | Resolution | Where |
|---|---|---|
| RG-H1 (rule G holds back a failed/dropped raise retry) | Raise exemption: rule G never gates `target > local + db` (or `> _reserve_last_ok_value` for rule L with no witness); C21; test `test_resend_gap_never_gates_raise`; mutation anchor; INV-R3 raise-timing clause; INV-R4 scoped to lowering/same desire | D1.3, 2, C21, D1 tests/anchors |
| RG-M1 (stamps vs two early returns) | Stamps at the top of `_record_reserve_dispatch`, before 9742-9749 and 9755-9760, own `try`; test + anchor | 4.5, D1 tests/anchors |
| RG-M2 (D1.4 ratchet re-asserts unlanded desire) | Stated the ratchet; DECIDED not to re-assert an unlanded raise (desire used only if ≤ floor or landed, else floor); never below floor; three tests + anchor | D1.4 |
| RG-M3 (CM change gate) | `test_cm_path_emits_nudge_and_stamps_attempt_only` uses a change-gated key; anchor | D1 tests/anchors |
| (b) stream resolver | `async_get_entity_id("sensor","mqtt",RESERVE_STREAM_UNIQUE_ID)`, reject disabled, operator precondition `expire_after: 60`; two tests; knob row | D1.1, 7 |
| RG-L1 (watchdog not gated by rule G) | Accepted, absorbed by D5; stated under INV-R4 | 2 |
| RG-L2 (no serial binding) | Residual on the card text (multi-home), not a new card | D1.1 |
| Carried (1)-(3) of rev 2 | All resolved by the re-review: field split confirmed; resolver specified; FAILED row precedes the early return in `force_redispatch` | 13 |

**Not resolved in rev 2 (carried) — all three closed in rev 2.1 by the re-review, kept for history:** (1) the `enphase_ev` field split (`control_updates.py` begin-snapshot, `coordinator.py:6714`) was taken from review 2's citations and not re-read on the Samba mount; the builder must confirm before writing trigger tests. (2) The stream entity's resolution path in code does not exist yet; D1.1 step 2 leaves its exact resolver to the rev-2 re-review. (3) The `force_redispatch` raise path's row/stamp ordering (does the FAILED row get written before or after the early return?) must be confirmed by the builder so the attempt stamp fires on that path.

---

---

## Plan review 2 (build-prediction) — 2026-10-23

Framing: "what will the builder get wrong reading this?" Read-only. Code read: `energy_battery.py` 5290-5335, 6983-7066, 7540-7660; `energy.py` 5700-5725, 7640-7670, 9813-9895; `energy_write_verify.py` `_compare` 1173-1210; on HA: `enphase_ev/number.py` 340-400, `control_updates.py` 20-115, 170-240, 268-277, `coordinator.py` 6714-6720. (No HVAC/presence surface touched.)

**Verdict: FIX-PLAN-FIRST.** Two plan claims are false against code (H1, H2), one deliverable as written re-creates the incident on a legal path (H3), and one decision rule is circular (H4). All are fixable in the plan text; none argues against the design.

### HIGH

**H1. D2 keys the nudge on the wrong field; a silent-drop loop is reachable.** The drop at `number.py:386` compares `battery_selected_backup_percentage` (`coordinator.py:6714`: `_battery_pending_reserve` if set, else effective). The number's *state* is `current_control_value(..., _battery_backup_percentage)` (`number.py:362-372`). While a control update is open, `ControlUpdates.value()` (`control_updates.py:170-177`) returns the *confirmed snapshot taken at `begin`* (`values[key] = deepcopy(confirmed)`, line ~92), not the requested value. So the two fields diverge exactly in the windows this cycle cares about: during pending, and while `pending` stays stuck true (section 1.3 shows `pending: true` 50 min after apply). Section 4.4 / C7 assumes "close enough, over-nudge costs 1 point". The dangerous direction is under-nudge: selected == target while state != target, so URA sends plain `target`, the integration drops it silently (no raise, no D5 row), the tap stamps the ledger = target (`energy.py:9876-9884`), and with local trusted and != target, D1 rule 1 re-sends every tick. Each send is dropped again. That breaks INV-R4 (up to 12/h) and INV-R1. D4 pages after 30 min but does not stop the loop.
*Repro shape:* `_battery_pending_reserve = 10` (stuck pending, as observed live 10-23), number state showing a different confirmed snapshot (e.g. 50 from an earlier change), local 50 trusted, target 10. Every tick: send 10, then `selected 10 == 10`, return.
*Fix (plan):* do not key the nudge on the cloud state. Key it on URA's own history: **nudge iff D1 decides to send AND (`|cloud - target| < 0.5` OR `ledger == target`, meaning the same value was already dispatched and local did not follow)**. This is field-agnostic and also covers C4 when an earlier send was dropped. Alternatively read `selected_reserve_percentage` from the profile-status sensor (`sensor.py:4121`) as the drop key. Add a test where cloud state != target, ledger == target, local trusted != target: the expected output is a nudge, not a plain resend.

**H2. D5's premise "a raised call does not stamp the ledger" is false for the timer path.** `_tap_write_verifier` stamps `_last_reserve_level = value` (`energy.py:9876-9884`) *before* it looks at `dispatch_result.ok` (status FAILED at 9888-9892). The dispatch loop calls the tap on every result, including raised ones (`energy.py:7660-7665`). Only `force_redispatch` skips the stamp on raise (it `return`s before step 5, `energy_battery.py:7586-7625`). Consequences:
- C11's claim "the ledger was not advanced, so the ledger term keeps retrying" is wrong. After a `control_change_pending` raise, ledger == target and rule 3 is silent.
- With local untrusted (unavailable or low-SOC guard) and cloud stale-equal, nothing retries. This is exactly the C4 residual, but now reachable through a raise rather than a pre-cycle silent drop.
- `test_raised_dispatch_does_not_stamp_ledger` would fail on unmodified code, and the plan leaves "check the tap ordering in the build" open. The builder will either (a) change the tap, which shifts `current_park_floor()` and pending-watchdog inputs on every FAILED write (a cross-site ripple the plan never scoped), or (b) delete the test.
*Fix (plan):* decide it in the plan. Recommended: the tap does not stamp the ledger when `dispatch_result is not None and not dispatch_result.ok`, mirroring `force_redispatch`. Enumerate the consumers of `_last_reserve_level` that see a changed value on FAILED (sweep `_commanded_ledger`, pending watchdog 2209, `current_park_floor`, KV persist `energy.py:2065`), and add a mutation anchor on the new guard.

**H3. The D1 `_hw` swap at the attain-floor bypass makes any stuck-high enforced value self-perpetuating, and it hides the result from D4.** The bypass sets `_level = max(floor, base)` and passes it to `_reserve_action` as the *desire* (`energy_battery.py:5302-5322`). That desire is then stamped as `_last_reserve_level_desired` (7017). With `base = local`:
*Repro (legal):* EVSE hold just released, local stuck at 98 (the 10-23 shape), cloud stale 10, arbitrage ATTAIN, inclement partial_hold floor 50 registered. Pre-cycle: base 10 gives level 50, so URA sends 50 (a partial release). With the swap: base 98 gives level 98, desire stamped 98, and deadband against local 98 gives no send. The stuck hold persists. D4 compares local to `_last_reserve_level_desired` (now 98), so it never fires, and INV-R1 holds vacuously because `target` itself became 98. The acceptance line "`_level` = 80, pre-cycle emits 50" enshrines the hazard; it only looks right when the high local value is a legitimate in-flight charge.
*Fix (plan):* "never lower an in-flight charge reserve" must be judged against **URA's own intent** (the ledger, or the desire stamp), not the hardware reading. Use `base = ledger` (`_last_reserve_level`), falling back to the desire stamp; use local only as the *deadband reference* inside `_reserve_action`. Add the repro above as a required test (expected: a send that lowers toward `max(floor, ledger)`). Also amend INV-R1/D4 to say `target` must not be derived from the enforced reading.

**H4. `_reserve_reference(target)` is circular at the `_hw` site.** The trust rule needs `target` (rule 4: `soc <= target + margin and local > target`), but at 5302 the target is `max(floor, base)` and `base` is what is being chosen. A builder will pick some order (likely `target=floor`), which changes the low-SOC guard outcome. *Fix:* split the API. `_local_witness_trusted(target)` is used only inside `_reserve_action`, after folding. The `_hw` site does not call it at all (per H3).

### MEDIUM

**M1. The low-SOC guard masks a real stuck-high reserve near the floor.** Rule 4 marks local untrusted for any `local > target` when `soc <= target + 3`.
*Repro:* SOC 11, target 10, local 98 (stuck), cloud 10 stale, ledger 10 (after H2's stamp-on-raise, or an earlier dropped send). The guard falls back to cloud, so there is no send. D4 excludes low-SOC ticks, so it stays silent. With `charge_from_grid` on and reserve 98 > SOC, the gateway imports from the grid. This is the cost class the card exists for.
*Fix:* bound the ratchet regime from above, e.g. untrusted only if `local <= soc + RESERVE_LOCAL_RATCHET_SPAN_PCT` (10-17 data: local 10-26 at SOC 4-9, so the span is about 20). D0-P1 fits the span. Add the repro as a C-row test.

**M2. `force_redispatch` nudge: the ledger, row and failure values are unspecified.** Step 5 stamps `live_desire` (`energy_battery.py:7631-7634`), the governor rows carry `live_desire`, and `record_dispatch_failed` carries `live_desire`. D2 says "stamp the dispatched ledger as nudge via the existing tap", but `force_redispatch` does not go through the tap. The builder will send 11 and stamp 10. *Fix:* state that all four sinks in `force_redispatch` (service value, step-5 ledger, both governor rows, `record_dispatch_failed`) use the nudged value. Add an assertion to `test_force_redispatch_nudges_same_value`.

**M3. Duplicate sends during the apply lag are not modelled in INV-R4.** The apply lag p90 is 461 s, longer than the 300 s tick, so local-primary re-sends the same target on the next tick in most normal changes. The duplicates are mostly dropped silently (selected == pending value), but each one writes an APPLIED `reserve_write` row and a verifier `schedule`. When the first write was a nudge (t+1) and the second is plain t (cloud state no longer equal to t), it is a *different* value inside the 600 s window, so it raises `control_change_pending` (`control_updates.py:71-76`) or lands as a second change. *Fix:* add an explicit in-flight rule. Rule 1 does not re-send when `ledger` is within the deadband of the value it would send (t or t+1) and `now - _last_reserve_level_at < CONFIRMATION_WINDOW_S` (600 s, a rung-1 constant mirroring Enphase's). Then the INV-R4 count includes dropped and deferred dispatches, and D0-P2 replays with this rule.

**M4. D3's "local confirms" inherits `_compare`'s `<= 2.0` tolerance, while the dispatch deadband is `>= 2`.** At exactly |local - commanded| = 2, D3 records CLOUD_STALE (no page) while D1 re-sends every tick. Pre-existing boundary, but D3 now suppresses the page that would have surfaced it. *Fix:* `_local_confirms` uses strict `< RESERVE_DISPATCH_DEADBAND_PCT`, or the plan states the boundary and tests it at 2.

### LOW

- **L1. Time source.** D4 dwell and any in-flight window (M3) must use `dt_util.utcnow()`, so `freezer` tests drive it, not `time.monotonic` or the wall clock. State this. D4's dwell start is RAM-only, so a restart resets it (C13 covers latches but not dwell); accept it and say so.
- **L2. D3 latch reset on a "fresh command".** A nudge followed by a plain re-send alternates the scheduled values (t+1, t), and each resets the latch, producing one `reserve_cloud_oracle_stale` per alternation. Key the latch on the desire, not the commanded value.
- **L3. "Trust requires `_envoy_reserve_sensor_eid` resolved".** `_local_reserve_witness_state` goes through `_local_entity_for`, which falls back silently. The builder needs a resolver that reports *which* path resolved. Name it in D1 (return the eid plus a `via_registry` bool), or the test for C14 will mock around it.

### INV-R4 loop proof (asked)
Once the nudge lands, the state is ledger = t+1, local = t+1, desire = t. Rule 1: |t+1 - t| = 1 < 2, no send. Rule 3: 1 < 2, no send. Low-SOC regime (local > t, SOC ≤ t+3): local is untrusted and the cloud reference is t or t+1, so there is no send. At target 100 the nudge is 99, local < target, |1| < 2. A restart mid-nudge KV-restores ledger t+1, which reaches the same state. **So the nudge itself cannot loop. The loops that remain reachable are H1 (wrong drop key, so a plain resend is silently dropped forever) and M3 (alternating t+1/t inside the 600 s window).** Both are closed by the H1 and M3 fixes.

### D3 masking a real failed write (asked)
There is no masking path while the trust rule holds and `_compare` is tight, because CLOUD_STALE requires that the gateway's own reading match. The residuals are M4 (a delta of exactly 2) and an "available but frozen" local sensor, which has not been observed (section 4.1). Neither needs more than the M4 fix and a sentence.

### Must-fix in the plan before build dispatch
H1 (nudge key), H2 (tap stamp-on-raise decided and enumerated), H3 (attain-bypass base = intent, not hardware, plus repro test and INV-R1 wording), H4 (API split), M1 (guard upper bound, fitted by D0-P1), M2 (`force_redispatch` sinks), M3 (in-flight rule and replay in D0-P2). M4 and L1-L3: fix in the plan text (one line each).

---

## Plan review 1 (completeness), 2026-10-23

Reviewer: ura-planner, Mode 2, completeness framing. Every site below was re-grepped on `develop` (c9e8f0015); the plan's lists were treated as hypotheses. HVAC/presence docs not applicable (energy-only surface).

**Verdict: FIX-PLAN-FIRST.** The site enumeration for writers is complete, but two load-bearing claims are false against code (H1, H2), the invariant/trip-wire are falsified by design under EVSE hold / drain-precedence (H3), and a prior-art local witness is missing (H4). All are plan edits, not redesigns.

### Independent site enumeration (result)
- Reserve `number.set_value` writers: exactly the governor allowlist `RESERVE_SET_VALUE_WRITERS` (`energy_const.py:2680-2702`): `_reserve_action` (`energy_battery.py:7062`), `force_redispatch` (`:7579`, `:7597`), `_apply_evse_battery_hold` (`energy.py:5701`). Pool/EVSE-amps/radar are non-reserve. No writer outside these. Matches the plan's 2-site D2 claim.
- `_reserve_action(` callers: `:5318` (attain bypass), `:6184` (blind), `:7147` (`_result`). Matches.
- Cloud `"reserve_soc_number"` reads: plan table 4.2 is complete (`energy.py:1149` is config mapping, `energy_write_verify.py:405/2467` are key maps).
- Local-witness consumers: plan lists 2219/1061/2347 but misses the `command_trail` three-way display at `energy_write_verify.py:2569-2595` (display; harmless, list it).
- Commanded-ledger consumers: plan 4.3 misses `_conduct_check_reserve` (`energy_write_verify.py:~2040`, reads `_commanded_ledger`) and the EVSE append clamp fallback (`energy.py:5662-5667`, ledger when desire None). The D2 nudge raises the ledger by 1 for both; benign, but must be listed.

### HIGH

**H1. D5 / C11 premise is false: the dispatch tap stamps the ledger on a FAILED dispatch.** `_tap_write_verifier` is called with the failed result (`energy.py:7656-7663`), and stamps `_last_reserve_level` at `energy.py:9876-9883` before and independent of `dispatch_result.ok` (the FAILED status is only applied to the governor row at 9890-9895). So after a `control_change_pending` raise the ledger already equals the failed value: the D1 ledger term will NOT retry (C11 wrong), and `test_raised_dispatch_does_not_stamp_ledger` fails against today's code. The plan must choose explicitly: (a) change the tap to not stamp on `not ok` (touches a shared ledger read by sweep, `_check` supersession, pending watchdog, conduct, overlay clamp, `current_park_floor`; a new Tier-3 ripple that needs its own consumer enumeration), or (b) keep the tap and drop the C11/D5 retry claim, relying on D1 rule 1 (trusted local) for retry and accepting the local-down residual. "Check the tap ordering in the build" is not acceptable for a load-bearing claim.

**H2. D1 rule 1 has no re-send spacing: it re-sends on normal apply lag and through Enphase pending episodes, and the nudge turns those into collisions.** Decision tick 300 s; local apply lag p90 461 s (B0-D2, oracle audit 3.2); the cloud reflects in ~61 s. Healthy repro: tick T sends 10 (cloud 98, local 98). At T+61 s the cloud reads 10. At T+300 s local is still 98 (lag in p50-p90 range): rule 1 sends, cloud == target, so D2 nudges 11, a second submission inside `CONFIRMATION_WINDOW_S = 600` raises `control_change_pending` or lands 11. Pending-episode repro (audit 5.3; 07-16 67-min case; 10-12..14 episodes): local stays old for over an hour, and rule 1 plus nudge fires every tick (12/h). That breaks INV-R4 and replaces the existing 15/30/60 ladder with its spacing gate (`energy_write_verify.py:2270-2285`, `CONF_PENDING_ATTEMPT_1_AGE_S`). Fix in plan: rule 1 re-sends only when the last dispatch of this desire is older than a named spacing (reuse `CONF_PENDING_ATTEMPT_1_AGE_S`, or a new rung-1 `RESERVE_LOCAL_RESEND_SPACING_S` ≥ 600 s), and the nudge never fires within 600 s of a prior reserve dispatch. Also D0-P2 cannot test the pending shape: the recorder starts 10-16, after the 10-12..14 episodes. P2 must say this, and a synthetic pending-episode test must be added (`test_reserve_reference_no_resend_inside_spacing`, `test_pending_episode_bounded_writes`).

**H3. INV-R1 and D4 compare local to the PRE-overlay desire, so both are falsified by design during every EVSE hold and DP transition.** `_last_reserve_level_desired` is pre-overlay; the hold/DP floors are folded only in `_apply_evse_battery_hold` (`energy.py:5586-5594`, `5682-5686`). Repro: EV charging, hold 98, strategy desire 10, local 98 for more than 30 min gives a D4 HIGH NM once a day per charge session, and an INV-R1 "violation" with no leak. D4's exclusions (stand-down, observation, low-SOC) omit this. Fix: INV-R1 and D4 key on the post-overlay effective desire. **REUSE** `WriteVerifier._effective_reserve_desired` (`energy_write_verify.py:1787`; already used by `force_redispatch` at `energy_battery.py:7546`), and add C16 "EVSE hold active / DP TRANSITIONED, local = hold value" with no D4 dwell to the case table. Same check for D1 rule 2: during a hold, trusted local 98 versus target 10 sends every tick, but the overlay rewrites it in place to 98 (`energy.py:5615`). That is byte-identical to today (the cloud also read 98), and the plan should state it rather than leave it implicit.

**H4. Prior-art miss: a second local reserve witness already exists, `sensor.envoy_stream_backup_reserve` (MQTT `meters.backup_soc`).** `PLANNING_envoy_local_witness_and_solar_follow.md` §1.6 and Cycle A4; `AUDIT_envoy_mqtt_trust_measurement.md` 3.2: the stream was up 98.65-99.78% of native-down time; 3.7, the reserve witness, is "UNTESTED, resolves organically". That is exactly the 7.4% local-down gap that drives C4, the ledger term, and Q3. Neither doc appears in §1.1. The plan must adjudicate REUSE-or-BUILD: at minimum add D0-P5 (stream reserve versus native and the gateway behaviour over 10-16..now, including native-down minutes inside episodes A-D), and either fold it in as a trust-tier-2 witness or park it with that probe as the trigger. Q3's "undetectable" claim is not true until this is answered.

### MEDIUM

**M1. D1 decision rules 2 and 3 contradict each other.** "Send iff any" versus rule 2 "means NO send, even if the cloud differs". With trusted local == target and ledger ≠ target (for example after a hold release where the overlay stamped 98 and the gateway already shows 10), rule 3 sends and rule 2 forbids it. State the precedence explicitly (recommended: rule 3 sends; rule 2 only overrides the *cloud* term), and add a test.

**M2. The attain-bypass call is circular.** `_reserve_reference(target)` needs `target` for the low-SOC guard, but at `energy_battery.py:5303-5317` `_level = max(_floor, _base)` and `_base` is what is being replaced. Specify: compute the witness with `target=_floor` (or a target-free `_enforced_reserve()` read) for `_base`, then call `_reserve_action(_level)`. Also state that the `_hw is None` / `compare_to` branch is unchanged.

**M3. The trust-rule API does not exist.** `_local_reserve_witness_state` (`energy_write_verify.py:1626`) does not report whether `_local_entity_for` used the Enpower fallback (`:419-427`), and it lives on `WriteVerifier`, not `BatteryStrategy` (which reaches it via `self._write_verifier`, `energy_battery.py:7037`). The plan says D3 imports the "same function" but does not say where it lives. Specify one owner (recommended: a `WriteVerifier.trusted_local_reserve(target, soc) -> (value|None, reason)` that calls `_envoy_reserve_sensor_eid` directly), and define the behaviour when `_write_verifier` is None (boot/tests: untrusted).

**M4. The CoordinatorManager path is not enumerated.** `_evaluate_battery` (`energy.py:7418-7451`) hands reserve writes to CM, writes a DEFERRED governor row, and never reaches the tap, so the D2 "ledger stamped with nudge via the existing tap" and the D5 classification do not hold on that path. State whether that path is live in this house. If it is, add it to D2/D5; if it is not, say so in non-goals.

**M5. Governor surfaces are missing from §1.** `PLANNING_reserve_write_governor.md`, the AST lint `quality/tests/test_reserve_write_chokepoint_lint.py`, and `RESERVE_SET_VALUE_WRITERS` are not cited. Add an acceptance criterion: "allowlist unchanged (D2 introduces no new writer; the nudge helper returns a value only)". Also missing from §1.1: `PLANNING_ec_reserve_witness_fix.md` (10-18 witness resolution, the "keep ±2" operator ruling that bears on naming the deadband) and `PLANNING_behavioral_write_verify.md`.

**M6. Unnamed numbers.** The nudge step `1`, the same-value tolerance `0.5`, and the D3/D5 episode coalesce windows are inline. Name them at rung 1 (`RESERVE_SAME_VALUE_NUDGE_STEP_PCT`, `RESERVE_SAME_VALUE_TOLERANCE_PCT`) and state the D3 latch-clear condition per site. The `_check` latch and the sweep REVERTED latch are separate state today (B-MED-2 coalesce at `energy_write_verify.py:995-1006`).

**M7. D3 sweep row is silent on the `is_pending_episode_active` interplay.** Today REVERTED emission is suppressed during an active pending episode (`energy_write_verify.py:1007-1021`). Specify the order of the `_local_confirms` check versus that suppression, and that CLOUD_STALE does not open or close a pending episode.

### LOW

**L1.** The blind-path exclusion (§4.2 row 6132) rests on "blind = Envoy down, so local is usually unavailable". That is not verified: blind is SOC/telemetry-blind. Either cite the blind trigger's file:line showing local is down too, or note that a blind tick with a healthy local witness keeps the pre-cycle (cloud) compare by design (INV-R3 holds either way).

**L2.** INV-R1's falsifier ("no `reserve_write` row whose value differs from the cloud's value at send time") is muddled after D2: a nudge row always differs. Restate: "no `reserve_write` row dispatched within the bound".

**L3.** The D1 Live criterion depends on an EVSE-hold release happening during the validation window. Add a fallback: any desire change of ≥ 2 while local is trusted produces a row within one tick, with `reserve_reference_source=local`.

**L4.** §4.3: the self-heal starvation detector (`energy_write_verify.py:586-621`) is today's only symptom-level detector of the same-value drop. Note that D3 suppresses it only while local confirms, so it stays the backstop for a nudge that is itself dropped.

### Checklist outcome
- Institutional context: present, REUSE/BUILD with file:line. Gaps: H4, M5.
- Invariants: R2 and R4 falsifiable. R1 is falsified by design (H3). R3 is fine once M1 is resolved.
- Knob ladder: mostly complete. Gap M6.
- Acceptance criteria: discriminating for D1-D3. The D5 test contradicts code (H1).
- Non-goals: explicit. Add the M4 verdict.
- D0 gating: P1/P2 gate the right deliverables. Add P5 (H4) and state that P2 cannot cover pending episodes (H2).

---

## Plan re-review (rev 2) — 2026-10-23

Framing: completeness on the rev-2 deltas + the three carried items + new defects introduced by rev 2. Code read on `develop` c9e8f0015: `energy.py` 1455-1480, 5424-5735, 7425-7470, 9651-9790, 9860-9925; `energy_battery.py` 5295-5325, 7010-7065, 7560-7660; `energy_write_verify.py` 425-480. On HA: `enphase_ev/number.py` 355-390, `control_updates.py` 160-180 + 265-277, `coordinator.py` 6712-6720, `battery_runtime.py` 2795-2810 + 4300-4335; `packages/envoy_mqtt.yaml` 95-104; entity registry.

**Verdict: APPROVE-WITH-FIXES.** The rev-2 disposition rows check out against code. One HIGH (the re-send gap can hold back a floor RAISE retry) and three MEDIUMs must be written into the plan text before build dispatch. None needs a design change.

### Carried items, resolved

**(a) enphase_ev field split: CONFIRMED.** The drop at `number.py:386-387` compares `coord.battery_selected_backup_percentage`, which is `_battery_pending_reserve` if set, else `battery_effective_backup_percentage` (`coordinator.py:6714-6718`). The displayed state is `current_control_value(coord, "battery_reserve", "reserve", _battery_backup_percentage)` (`number.py:362-372`). `ControlUpdates.value()` (`control_updates.py:170-177`) returns the stored `values[key]` while an update is held or not yet confirmed, otherwise the fallback. So the drop key and the displayed state are different fields even when no update is open (`effective` vs `_battery_backup_percentage`, the latter written only on a non-stale profile read, `battery_runtime.py:2805`). D2 trigger (b), keyed on URA's own landed request, is the right fix. Builder: no further mount read needed. Trigger tests can model the two fields separately.

**(b) Stream witness resolver: does NOT exist. Must be BUILT.** No code reference to `envoy_stream`, `backup_soc` or `stream_backup` anywhere in `custom_components/` (grep). Prior plan A4 (`PLANNING_envoy_local_witness_and_solar_follow.md:289`) was never built. Facts the plan should pin:
- The entity is an MQTT YAML sensor (`packages/envoy_mqtt.yaml:97-104`), platform `mqtt`, unique_id `envoy_stream_backup_reserve`, with **no serial in the unique_id**. The `_envoy_reserve_sensor_eid` serial-anchored pattern cannot be reused.
- Specify the resolver as `er.async_get_entity_id("sensor", "mqtt", RESERVE_STREAM_UNIQUE_ID)` with a module constant `RESERVE_STREAM_UNIQUE_ID = "envoy_stream_backup_reserve"` (rung 1). Reject when the entry is disabled, mirroring 467-471. Never use a hard-coded entity_id.
- Freshness comes from `expire_after: 60` in the HA YAML package, so a dead stream goes `unavailable` rather than holding a frozen value. URA cannot see that setting. State it as an operator-side precondition in the README and under the `RESERVE_STREAM_WITNESS_ENABLED` knob. It is not portable to other homes (multi-home rollout) and has no binding to a specific Envoy (LOW).

**(c) `force_redispatch` FAILED row before the early return: CONFIRMED.** In the raise branch, `record_dispatch_failed` runs (`energy_battery.py:7596`), then the FAILED `_record_reserve_dispatch` row (7607-7616, reached through `getattr(self._coord, ...)`), then `return` (7625). The APPLIED row comes after the step-5 ledger stamp (7629-7652). Both branches reach `_record_reserve_dispatch`, so the attempt stamp fires on the raise path. Caveat: see M1.

### HIGH

**RG-H1. Rule G holds back the retry of a failed or dropped floor RAISE, which pre-cycle code retried on the next tick.** Rule G suppresses a rule-T or rule-L candidate when the last *attempt* had the same value within 900 s. A FAILED attempt is stamped too (4.5) but is not in flight. With a trusted witness, rule T replaces rule C, so the pre-cycle cloud-driven retry is gone. INV-R3 covers only the no-witness case, so it does not protect this. This affects only re-sends of the *same* value. A first escalation, an EVSE hold engage (overlay append, `energy.py:5700`, not routed through `_reserve_action`) and a DP floor are never gated. The cases that are gated:
- *Repro 1 (transient raise):* inclement partial_hold escalates the floor, so the target goes 10 → 50. Local trusted at 10, cloud 10, SOC 60. At T the send of 50 raises (`TimeoutError`, or `control_change_pending` because a URA lowering went out at T-200). Attempt stamp is 50@T; landed stamp is not advanced. At T+300, rule T is a candidate (|10−50| ≥ 2), but the attempt value is 50 = target and the gap is still running, so the result is `in_flight` and no send. **Pre-cycle:** cloud 10 ≠ 50, so it sends at T+300. Rev 2 holds the reserve below the storm floor for an extra 600 s (non-pending raise) or about 300 s (pending window clearing at T+400). All of these are legal defaults.
- *Repro 2 (silent drop of a raise):* `_battery_pending_reserve` is stuck at 50 and the display shows 10. URA sends 50, it is dropped, and the landed stamp is 50. The trigger-(b) nudge to 51 waits the full gap.
- **Fix (plan text):** rule G never gates a **raise**, meaning a candidate with `target >= local + RESERVE_DISPATCH_DEADBAND_PCT` (rev 2.2: `>=`, so a raise of exactly the deadband is never gated — INV-R3 raise timing) (or, for a rule-L candidate with no trusted witness, `target > _reserve_last_ok_value`). Raises keep the pre-cycle every-tick retry (≤ 12/h, inside the churn cap; D5 already stops the pages). Alternative, weaker: gate only when the last attempt's status ≠ FAILED. That does not cover Repro 2. Add C21 "floor raise fails at T → re-sent at T+300" and the test `test_resend_gap_never_gates_raise`, with mutation anchor "drop the raise exemption → RED". Amend INV-R4 to say "for one stable lowering/same desire". Amend INV-R3 or add an INV stating that no floor raise is ever sent later than pre-cycle code would send it.

### MEDIUM

**RG-M1. `_record_reserve_dispatch` has two early returns before any place a stamp could go.** One is the change gate `return  # SKIPPED_ALREADY_CORRECT` (`energy.py:9742-9749`; it applies to timer/evaluate APPLIED/DEFERRED rows when the key matches and `pre_state == value`). The other is `db is None → return` (9755-9760, the normal case in unit tests). If the builder appends the stamps at the end, as "the producer is `_record_reserve_dispatch`" suggests, then rule G and rule L go silent in every test without a DB. In prod the change-gated steady re-sends are skipped, and so is the stamp. Plan text: stamp **first**, right after `value_i` is computed and before the gate, inside its own try. Add the test `test_attempt_stamp_written_without_database_and_when_row_gated`. The 4.5 wording "every status, all four dispatch points" is correct only if this ordering is followed.

**RG-M2. The D1.4 desire-first base is self-referential (a ratchet). The plan does not say so.** `_reserve_action` stamps `_last_reserve_level_desired = max(reserve_level, floor)` on every call (`energy_battery.py:7017`), including the attain-bypass call itself. So in ATTAIN, `base_N = level_{N-1}`. The level never comes down while the bypass runs, and its seed is whatever desire was last stamped before ATTAIN. Post-hold-release behaviour is correct (the overlay never writes the desire, so the desire is max(floor, pre-hold desire), not 98; review-2 repro holds). One new behaviour is not stated: a pre-ATTAIN desire that **never landed** gets re-asserted.
- *Repro:* arbitrage CHARGE desire 80, write dropped or failed, local 10. Enter ATTAIN with floor 50: base = desire 80, so level 80, and rule T sends 80. Pre-cycle: base = hw 10, so level 50.
That may be the intended "in-flight charge" semantics, but it is a cost-relevant raise (grid charge to 80 during ATTAIN). The plan must state it and pin it with a test either way (`test_attain_base_reasserts_unlanded_prior_desire` or the opposite). Also add the floor-drop case (floor 80 → 20 within ATTAIN keeps 80, same as pre-cycle).

**RG-M3. Placement of rule G against the CM path's change gate.** The CM path's DEFERRED row is change-gated (path `evaluate`, so not exempt). Without the RG-M1 ordering, a CM send at the same value as the memo leaves no attempt stamp, and the next timer tick re-sends inside the window. RG-M1 covers it. Listed separately so framing C anchors it: `test_cm_path_emits_nudge_and_stamps_attempt_only` must use a gated key.

### LOW

- **RG-L1.** `force_redispatch` (watchdog, 900 s ladder anchored on `_last_reserve_level_at`) is not gated by rule G. A D1 send at T and a watchdog retry at T+<600 can collide in the Enphase window. This is pre-existing. D5 now absorbs the resulting raise. State it under INV-R4's "all paths ≤ 12/h".
- **RG-L2.** The stream resolver has no Envoy serial binding (see (b)). Acceptable for one install. Card it for multi-home.

### Re-verified rev-2 claims (hold)
- Tap stamps the ledger before the `ok` check (`energy.py:9876-9883`) and records FAILED when `not dispatch_result.ok` (9890-9898): holds.
- CM path is live on TOU transitions and skipped in observation mode (`energy.py:1464-1475`). Its row is DEFERRED (7450-7454): holds.
- EVSE hold: the overlay rewrites in place (5614) or appends unconditionally each tick (5700). One reserve action per tick, value = hold, before and after the cycle (C16): holds. Rule G never sees overlay writes as gated sends.
- EVSE append clamp fallback (`energy.py:5652-5669`: desire, then ledger): holds as tabled.
- Low-SOC guard, attain no-witness branch and `compare_to` behaviour (7024-7027): consistent with 7010-7065.

### Must-fix in the plan before build dispatch
1. RG-H1: raise exemption in rule G, plus C21, a test, a mutation anchor, and the INV-R3/INV-R4 wording.
2. RG-M1: stamp position in `_record_reserve_dispatch` (before the change gate and the no-DB return), plus a test.
3. RG-M2: state the D1.4 ratchet/re-assertion semantics and pin them with a test.
4. (b): specify the stream resolver (`mqtt` platform + unique_id constant, disabled check, `expire_after` precondition in the README).
