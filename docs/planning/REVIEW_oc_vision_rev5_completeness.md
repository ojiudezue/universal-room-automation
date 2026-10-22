# REVIEW — OC self-fixing-house vision rev 5: completeness + grounding (Tier 3 plan review, framing 1 of 2)

Reviewed: `VISION_optimization_coordinator_self_fixing_house.md` (rev 5) and `PLANNING_oc_request_fix_dispatcher_SEED.md`. Neither doc was edited.
Reviewer read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `docs/architecture/SENSOR_FLEET_CLASSES.md` completely before reviewing. No §10 ledger claim is re-asserted here.
Method: every file:line in the vision was opened; services were re-enumerated from `services.yaml` and every `hass.services.async_register` in the package; buttons were listed from `button.py`; OC prior art was grepped in `docs/planning/`.

**Verdict: ⚠️ direction sound, not build-ready.** 2 CRITICAL, 6 HIGH, 7 MEDIUM, 4 LOW. Scope: BROAD (a vision, which is acceptable), but slices 1-2 need these fixes before any plan is cut from them.

---

## Citations that check out

`__init__.py:6355` memory_query, `:6611` test_notification, `:6213` reapply_radar_settings, `:6186` fan_recheck_force_restore; `optimization.py:4514` `_check_reserve_role_hard_deny`; `security.py:1880` `honor_optimizer_intent`; `notification_manager.py:1334` `async_notify`; `presence.py:101` `_run_fan_recheck_tick_for_rooms`; `energy.py:910` `_lifetime_production_hwm`; `energy_billing.py:576` `reseed_cycle`; `hvac_preset.py:259` `manual_guard_verdict`; `hvac_excursion.py:597` `is_borrow_active`; `hvac_const.py:1546` `DYNAMIC_DOMAIN_ALLOWLIST`; `fan_policy_oracle.py:588` `actuate`; `memory_facade.py:608-627` `outcome()` is a stub (returns `insufficient_history`); `memory_writers.py:29-43` boundary text. Budget arithmetic in the table reproduces from the stated formula (Opus $2.34, Sonnet $1.17, Haiku $0.066).

---

## CRITICAL

### C1. "Hard-denied in code, not by prompt" has no code in slices 1-2
§3 says the never-grantable list is enforced in code, and §8 says "tool tier gates are enforced in code". But §5 runs the agent **outside HA** as "a scheduled Claude session like today's (ha-mcp, ssh, the URA DB, the board)". In that harness the session's tools include `ha_restart`, `ha_call_service` (any domain), `ha_config_set_automation`, `ha_remove_entity`, `ha_manage_backup`, `ha_manage_hacs`, `ha_set_integration` and a shell on the HA host. Nothing in URA's code sits between those tools and the house. Today's only gate would be the prompt plus whatever Claude Code permission config the scheduled session runs with, and neither doc names one. The same sessions also read entity names, logs and messages, which §8 itself lists as an injection vector.
**Fix:** add a slice-1 deliverable "harness enforcement". (a) The scheduled session gets an explicit allowlisted tool set: read-only ha-mcp tools, read-only DB (the `ura-sqlite` MCP, or a read-only SSH user), no `ha_call_service`, no shell. (b) Every R1 action goes through ONE URA service (`request_fix`, moved from slice 2 to the first slice that acts) whose handler enforces the tier, the type registry and the deny list in Python. (c) Acceptance: a test drives each never-grantable call through the harness and the service and shows it refused, and the harness config is committed. This test fails today, which makes it discriminating.

### C2. Slice-0 eval answers leak through the knowledge pack
The eval cases are the 10-21 fixes plus READMEs and cards. §3 loads "URA docs ... operator doctrine: CLAUDE.md and the feedback memories" fresh on every run, and the slice-0 catalogue (`docs/planning/oc_eval/tools.json`) includes `read_doc`, `read_code` and `kanban_search`. Those surfaces already contain each case's root cause: README_v5.103.83 (exit rows, dwell anomaly), the EC-SOLAR-LIFETIME-COUNTER-FLAP-1 code comment at `energy.py:911`, HVAC §9.3/C27 (Seeed radar following the Jaya fan), and HVAC header line 73 (S10 latch NMs at MEDIUM). A model can score "correct root cause" by retrieving the write-up, not by diagnosing. Small models that retrieve well would then pass a bar they cannot meet live.
**Fix:** each case's frozen snapshot has a **cutoff time before the fix**. `read_doc`, `read_code` and `kanban_search` answer from the repo at the pre-fix commit, with the post-fix README, memory and card bodies removed. Add a leakage check to slice-0 acceptance: for each case, grep the frozen corpus for the expected root-cause string, and the case is invalid if it is found.

---

## HIGH

### H1. R1 contains occupant-visible actions, against R1's own definition
R1 is defined as "reversible, **not occupant-visible**" and allowed "including overnight".
- **Request a fan recheck** pauses a running fan, which turns it off (`presence_fan_recheck.py`; all writes go through `hvac_fans.FanController._set_fan_state`; PRESENCE §6 item 3). That is occupant-visible. In bedroom and media rooms it is vetoed during `FAN_TRUST_STATES` precisely because a sleeper is there.
- **`fan_recheck_force_restore`** turns a fan back on.
- **Clear a stuck-sensor latch** re-admits a sensor that URA quarantined. The 4 h stuck rule (`coordinator.py:364`) is what removed the fan-tracking Seeed radar in HVAC C27. Re-admitting a stuck-on sensor holds the room, and with it the HVAC zone, occupied: lights, fans and conditioning all follow. There is also no "latch" to clear. The stuck set is recomputed each tick from `_stuck_sensor_since` (`coordinator.py:2297-2324`). A "clear" is a timestamp reset that silently re-arms a 4 h window. The gold pattern is a `SensorExclusionSet` client release (PRESENCE gold-patterns table).
- **Reload one config entry** reloads ZHA/Z2M, Hue, Lutron or Shelly, which blinks or drops every device on that entry. CLAUDE.md calls Sonoff/Tuya "a single account entry covering many devices". Reloading Envoy is the 2026-06-12 EC restore-poisoning shape (memory `project_envoy_boot_incident_2026_06_12`).

**Fix:** move fan recheck and force-restore to R2 (types P2-adjacent). Move stuck-sensor clear to R2 or R3, defined as a `SensorExclusionSet` client release rather than a timestamp reset. Make config-entry reload R1 only for an **integration allowlist** (single-device entries; never Zigbee/Z-Wave coordinators, cloud multi-device accounts, Envoy/EC inputs or cameras) and R3 otherwise. §8 says "every R1 tool checks that it is not occupant-visible before acting". Define that predicate per tool, or delete the sentence.

### H2. The tool inventory misses reachable surfaces
The task asked for everything the agent could reach that is neither allowed nor excluded. Re-enumerated:
- **URA services not classified** (registered at `__init__.py:6177-6665`, `notification_manager.py:1169`): `clear_house_state_override`, `test_safety_hazard` (fires a safety hazard), `authorize_guest`, `add_expected_arrival` (drives pre-arrival HVAC), `acknowledge_notification`, `nm_mute_person_channel` (can silence the operator's own pages), and `test_inbound` (registered, not in `services.yaml`).
- **`button.press` is not mentioned anywhere.** URA exposes 22 button classes (`button.py`), including `ReloadRoomButton` (a URA entry reload, the watchdog hazard), `VacuumDatabaseButton`, `MemoryCompactNowButton`, `EVSEForceChargeButton` (money), `ClearBayesianBeliefsButton`, `ResetPresenceTimersButton`, `_ACRampButton` (HVAC writes), `OptimizerResetSettingsButton` and `OptimizerConfirmEscalationButton`.
- **`switch.turn_on/off` on URA's own switches** (kill switches, Automation/Manual Mode, Override Occupied/Vacant, arrester, S10 switch 01). Only raw `switch.*` on devices is listed.
- **Non-URA:** `input_*` helpers, `cover.*`, `media_player.*`, `vacuum.*`, `water_heater.*`, `camera.*`, `ai_task.*` (spend), `homeassistant.update_entity` and `update.install`.

**Fix:** replace the enumerated deny list with **default-deny**: the allowed set is the table, and everything else is denied. Keep the "never grantable" list as the subset that can never be promoted, and add `button.press` on every URA button, URA switch writes, `test_safety_hazard`, `nm_mute_person_channel`, `authorize_guest`, `update.install` and `ai_task.*`.

### H3. Both an in-HA OC executor and the new agent would actuate; the doc keeps one and lints against it
`optimization.py` already has a live action executor that makes raw `hass.services.async_call(domain, action, …)` calls at `:4677` and `:4826` behind the autonomy ladder, kill switch and veto broker. §7 keeps "autonomy ladder, kill switch, denylists" as backstops. Slice 3 then requires "0 raw service calls into an owned domain (lint)", which that executor violates by construction. The vision does not say whether the old executor is retired, forced to L0, or routed through `request_fix`. Separately, the allowlist reason text and HVAC §4.2 still cite `optimization.py:3546/:3688`, which are now Prediction-Validation code (stale lines; the calls sit at ~4677/~4826).
**Fix:** state that the legacy executor is clamped to L0/L1 (advisory/shadow) from slice 1 onward and deleted or rerouted in slice 3. Name the lint's scope. Correct the stale line references in `hvac_const.py:1543` and HVAC §4.2/§4.3 (code wins, so fix the doc).

### H4. Prior OC plans are not consulted, and a parked trigger fires
`PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md` (the six-rung ladder, `SIGNAL_OPTIMIZER_INTENT` handshake, `ai_task` LLM tier, cost levers, quiet hours) is not cited by either doc. Its **Appendix C D3 "reload-as-recovery: PARKED"** is exactly vision R1 "reload one config entry", and the parked design set seven safety conditions that rev 5 drops: provenance allowlist, recoverability gate, single-shot per outage, rate/daily cap, quiet hours, shadow-first, and an observable row. Also not cited: `PLANNING_OC_phase5_handshake_and_admin_surface.md`, `CRITIQUE_audit_optimization_coordinator_2026-07-10.md`, `PLANNING_audit_optimization_coordinator.md`, and the existing `optimizer_llm_task_entity` / `ai_task` plumbing (the vision says only that "`ai_task.ollama` exists"). The seed's request_fix "gates in order" duplicates the v2 chokepoint (rung × dimension × rate cap × quiet hours × kill switch + broker).
**Fix:** add an institutional-context section to the vision and the seed with REUSE/BUILD per piece. Adopt the seven D3 conditions as the R1 reload spec. State whether `request_fix` IS the v2 chokepoint (extend it) or a replacement (and then why).

### H5. P3 duplicates S1 and the lease sweep, and its check-back is not decidable
HVAC §9e: since W1-B, S1 reclaims any `manual` zone to its target preset unless gates (a/b)/(c)/(d)/(e) hold, and the excursion lease-expiry sweep (`_auto_return`) returns borrows past `stale_ts`. An "unreleased borrow" is therefore either inside its lease, where gate (e) makes a P3 write wrong, or past it, where the sweep and S1 already restore. P3's only remaining case is one where S1 itself is refusing, which is a gate the agent should not override. Its check-back "no manual-hold flag" assumes a reliable manual oracle, but HVAC C20/C22/C23 show neither Carrier feed is reliable, and ecobee has no `hold_activity` at all.
**Fix:** drop P3 as a fix type, or redefine it as "diagnose why S1/the sweep did not reclaim" (R0) and card the defect. If it is kept, the check-back must use the W1-A `climate_write` ledger and physical evidence (blower/temperature), not `preset_mode`/`hold_activity`.

### H6. The budget model understates cost, and the Haiku row conflicts with the run design
- **Cache reads.** The formula books 1.5M cache-read tokens for 30 round-trips over a 60k pack plus 300k of accumulating tool results. Re-reading a growing prefix each turn costs about Σ(60k + i·10k) for i = 0..29 ≈ **6.2M**, not 1.5M. Sonnet becomes ≈ $1.6/night (≈ $49/month), which is still above the cap. Cache writes (1.25x on each new suffix) are omitted.
- **Haiku pricing tier.** The Haiku row assumes "≤ 100k prompt" while the same run passes 100k by about turn 4. By the doc's own note, prompts above 100k cost 5x, so most Haiku turns pay the 5x rate.
- **Token bounds disagree.** §3b caps tool results at 200k per run, but §5b budgets 300k.
- **Event-triggered runs are uncapped.** One restart storm (8 restarts, memory `project_reload_storm_refuted_restart_storm_live`) is 8 extra runs.

**Fix:** recompute with the cumulative-prefix formula and both Haiku tiers, align 200k vs 300k, and add a rung-3 knob `optimizer_agent_event_runs_per_day_max`. Slice 0's measured per-case cost replaces all of this, so state that the $25 fit is unproven until then.

---

## MEDIUM

**M1. Sleep gate vs "R1 overnight" is undefined at the edges.** "House sleeps" is not tied to a signal. Name it: `HouseState.SLEEP`/`WAKING`, NM quiet hours, or the per-room `FAN_TRUST_STATES`. GUEST, with a guest asleep, is not covered. Fix: one predicate, `house_state ∈ {sleep, waking}` OR a GUEST night, read live at actuation, used by both R1 occupant-visibility and R2.

**M2. Paused rooms and manual holds are not gates for P1/P2.** A room with the Automation switch off or Manual Mode on deliberately keeps its lights and fans (PRESENCE §4.5, HVAC §4.2b, `const.room_automation_paused`). A fan under a manual-ON hold is a person's choice. As written, P1/P2 would turn both off. Fix: P1/P2 refuse when `room_automation_paused`, when a manual-ON hold is live, or when Fan Mode is Off/room-owned. Also cite `light_policy_oracle.py` for P1, since §3 names only the fan oracle.

**M3. P1's premise needs a producer check.** If the room's vacancy-off already runs, a light left on in a vacant room means the room is paused, an actuator is offline (CLAUDE.md troubleshooting: check `sensor.<room>_unavailable_entities` first), or a person turned it on. None of those is fixed by re-issuing the vacancy-off. Fix: P1's preconditions read the actuator's availability and the room's last automation decision. Measure how often the case occurs (a one-shot recorder probe) before carding P1. That is measure-before-build, and P1 may have near-zero true positives.

**M4. Same tool, two tiers.** `reapply_radar_settings` is R1 in the §3 table and R2 type P5 in §2a. Fix: pick one. It changes occupancy sensitivity, so R2/P5.

**M5. R1 demotion is undefined.** "A failed check-back auto-demotes its fix type" (slice 2) applies to promoted R2 types. R1 types are allowed alone from the start, so it is unclear what they demote to. Fix: R1 types also carry a state (act-alone / propose-only). A failed check-back moves that type to propose-only, and only an operator tap restores it.

**M6. Acceptance criteria that do not discriminate.**
- Slice 0 "0 R3 attempts": the slice-0 catalogue (`oc_eval/tools.json`) contains no R3 tool, so the metric reads 0 whether the model is safe or not. Fix: include honeypot cases where restart or a URA reload is the tempting fix, and expose an R3 tool as `propose_action` only, counting any direct-call attempt.
- Slice 1 "operator rates ≥ 80% correct over 1 week": with 5 diagnoses, 4/5 passes. Fix: a minimum n (for example ≥ 25 rated diagnoses) and a stated non-pass outcome (extend the week, not ship).
- Slice 0 ≥ 80% on ~12-15 cases: one case is about 7 points. State the case count and treat it as a floor.

**M7. Outside-HA `notify` path.** "NM digest/page (`test_notification` / NM `async_notify`)": `async_notify` is in-process Python and cannot be reached from an outside session, and `test_notification` is a test service. Fix: name the real path (a `request_fix`-style URA service `optimizer_agent_digest` that calls `async_notify` with a fixed coordinator id and severity). Otherwise slice 1 has no compliant way to send the morning summary.

---

## LOW

- **L1. §3 contradicts itself.** Line 135 says build the thin dispatcher in slice 2. Line 141 says "No unified request API." Delete line 141 or qualify it.
- **L2. Header is stale.** It says "Rev 4 adds…" and "Status: vision for operator approval", while the title says rev 5 approved. The revision history has no rev-5 entry.
- **L3. Knob ladder gaps.** Numbers with no knob or rung: the promotion bar (20 proposals / 90%), the slice-0 bar (80% / 95%), the §3b bounds (50 entities, 200k tokens, 7 d, 24 h), the check-back windows (10/30/15 min, 3 d), and the "once per month" page. Suggest rung 1 for the promotion and eval bars (changing them should require review) and rung 3 for the per-run bounds. Goals (five selects plus a bill-cap number) are a new config surface. Grep confirmed no existing `optimizer_agent_*` or `budget_usd` constant (NEW, justified).
- **L4. Seed open questions miss two items.** Idempotency/dedup of a repeated `request_fix` for the same (type, target) inside its check-back window, and what the service returns to the outside agent (a response schema with `SupportsResponse`, as `memory_query` does).

---

## Parked-plan triggers this vision fires
| Parked item | Where | Fired by |
|---|---|---|
| D3 reload-as-recovery | `PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md` App. C | R1 "reload one config entry" (H4) |
| `optimization.py` climate routing (`DYNAMIC_DOMAIN_ALLOWLIST` card HVAC-SETHVACMODE-CHOKEPOINT-1 scope) | `hvac_const.py:1543-1553` | §3 R2 "remove optimization.py from the allowlist" (H3) |
| `bayesian_predictor.get_anomaly_score` DELETE candidate | PRESENCE §9 (v5.103.83 note) | eval case "Bayesian arrival-vs-dwell mismatch" relies on its pre-fix state (C2 cutoff) |
| `HVAC-WRITE-CONFIRMATION-ORACLE-1` | HVAC §9e/§11 | any P3 check-back (H5) |

## Summary
| Severity | Count |
|---|---|
| CRITICAL | 2 (C1 enforcement absent outside HA; C2 eval leakage) |
| HIGH | 6 (H1 tier misclassification; H2 inventory gaps; H3 legacy executor; H4 prior art + parked D3; H5 P3; H6 budget) |
| MEDIUM | 7 |
| LOW | 4 |
