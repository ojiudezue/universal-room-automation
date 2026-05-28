# PLANNING v4.7.x — EV TOU Pause Hardening + Sub-Switch State Recovery

**Status:** Plan ready for build
**Tier:** Tier 2 (multi-file, new button/sensor surface, addresses EC startup race deferred work)
**Trigger:** 2026-05-27 live cost-bleed incident: `switch.ura_energy_coordinator_ev_tou_management` was silently OFF after today's Envoy-cascade-driven sub-switch deferred-restore-exhausted state, causing EV to charge at mid-peak ($0.13/kWh × 7.3 kW ≈ $1/hr leak). User had no visibility. Discovered via live diagnostic.

**Predecessor evidence:** `memory/project_ec_startup_race_evidence.md` — 2nd HA-restart-fix of EC `not_initialized` on 2026-05-19. Today's boot-timeline data is the empirical evidence the resilience cycle was waiting for.

---

## Goals

Three intertwined symptoms surfaced today:

1. **Sub-switch state loss after EC startup race.** EC sub-switches (5 of them: grid_import_cap, load_shedding, excess_solar_charging, grid_arbitrage, ev_tou_management) exhaust their deferred-restore retry chain when EC coord init is delayed (Envoy validation race, etc.) and stick at constructor seed values — NOT the user's saved values. User has no signal that this happened. Silent state divergence.

2. **EV TOU pause can be defeated by manual HA-side override.** Even when the master switch is on, the `_paused_by_us` short-circuit in `energy_pool.py:283` prevents URA from re-pausing an EVSE that a user manually re-enabled. Policy = "no grid charging during mid-peak/peak" → silently violated on every manual override.

3. **Energy situation has no plain-English explanation.** Battery reserve at 88%, grid importing 11 kW — and the user can't tell what URA is optimizing for without digging into sensor attributes.

This plan bundles fixes for all three under one Tier 2 cycle.

---

## Tier classification

Tier 2 (not Tier 2-DB). Justification:
- Touches `database.py` DAO definitions? No.
- Migrates ≥3 callers to a new DAO? No.
- Changes payload shape of dispatched events? No.
- Adds behavioral test infra against real schemas? No.

Two independent staff-engineer reviews (Reviewer A = correctness + EC startup race; Reviewer B = async lifecycle + cross-coordinator). Tag `pre-review-v<version>` before any review fixes.

---

## Deliverables

### D1 — Strict EV TOU re-pause (drop `_paused_by_us` short-circuit)

**File:** `domain_coordinators/energy_pool.py`
**Effort:** ~10 LoC + 3 tests
**Bug class prevention:** #23 (observation-mode gating preserved)

**Change:** the bookkeeping short-circuit `if state["is_on"] and evse_id not in self._paused_by_us:` becomes `if state["is_on"]:`. URA re-pauses idempotently each tick. Manual HA-side override is reversed within ≤5 min. Strict policy enforcement.

**Excess-solar exception preserved** (already handled before this branch in the existing code).

**Acceptance criteria:**
- **Verify:** Mid-peak active, user manually turns on EVSE → URA turns it off on next decision cycle (≤5 min)
- **Verify:** User keeps re-enabling → URA keeps pausing (no give-up)
- **Verify:** Excess solar engaged during mid_peak → EVSE stays ON (existing exception unchanged)
- **Test:** `test_ev_tou_repauses_after_manual_override`, `test_ev_tou_strict_during_peak`, `test_ev_tou_excess_solar_exception_preserved`
- **Live:** Toggle EV switch ON during mid-peak; observe URA repause within one decision tick

### D2 — Sub-switch state restore reliability (the EC startup race fix)

**File:** `switch.py` (the `_ec_switch_factory`)
**Effort:** ~50-80 LoC + 5-6 tests
**Bug class prevention:** #5 (startup race), #10 (cross-restart state loss), #38 (async_listen unsubs)

**Root cause documented:** the `_ec_switch_factory` deferred-restore retry chain (currently 3 retries with short backoff) gives up when EC coord init takes longer than the retry budget. The retry-exhausted log fires; switch sticks at constructor seed (NOT user's saved RestoreEntity value). User has no signal.

**Proposed fix — two-layer approach:**

**Layer A — extend the retry chain to be unbounded with exponential backoff.**
- Replace the fixed-N retry chain with an `async_track_state_change_event` listener on a sentinel entity that fires when EC coord becomes available
- OR: subscribe to a new `SIGNAL_ENERGY_COORDINATOR_READY` dispatcher signal that EC fires once init completes
- Either way: retries are unbounded but event-driven (not timer-spam)

**Layer B — push-from-coordinator on init completion.**
- When EC coord finishes init, it walks its 5 sub-switch entities and pushes the SAVED option values into them
- Belt-and-suspenders with Layer A; ensures the OPTION → SWITCH sync is the authoritative direction (not switch trying to ask EC)
- Fires `async_write_ha_state()` on each sub-switch entity to refresh UI

**User-visible safeguard:**
- New `binary_sensor.ura_energy_coordinator_sub_switches_synced` exposing whether the 5 sub-switches all match their CM-options values
- When False (mismatch), shows attrs naming the divergent switches
- Repair issue raised if mismatch persists >10 min

**Bug class #19 (untracked tasks):** no new `async_create_task` calls; the event-driven retry replaces the timer-driven retry chain (fewer tasks, not more).

**Acceptance criteria:**
- **Verify:** Force EC coord to delay init by 60s (e.g., Envoy temporarily disabled). 5 sub-switches MUST adopt their saved values when EC finishes init.
- **Verify:** Restart HA mid-incident (sub-switches partially restored). On next boot, all 5 sub-switches reach their saved values.
- **Verify:** `binary_sensor.ura_energy_coordinator_sub_switches_synced` reports True post-init; False during the mismatch window.
- **Test:** `test_sub_switch_state_restore_after_delayed_ec_init`, `test_sub_switch_state_restore_after_restart_mid_incident`, `test_synced_sensor_reports_mismatch_correctly`, `test_no_untracked_tasks_from_retry_chain`
- **Live:** Reproduce today's symptom (disable Envoy briefly to trigger EC validation skip, then re-enable). All 5 sub-switches must recover to saved values within 60s of EC re-init.

### D3 — URA-side admin override for EV TOU pause

**Files:** `button.py`, `switch.py`, `sensor.py`, `domain_coordinators/energy_pool.py`
**Effort:** ~80-120 LoC + 4-5 tests
**Bug class prevention:** #23 (observation mode), #35 (button refresh signal), #21 (UTC vs local timezone for expiry)

**Design:** an URA-side button that opens a time-limited override window. NOT a casual switch (per user mandate "really intentional admin action"). Specifically:

- **`button.ura_energy_coordinator_evse_force_charge_30min`** — single-action button. Pressing it:
  - Opens a 30-minute window during which EV TOU pause is bypassed
  - Records the activation timestamp + reason (default "manual admin override") to URA DB
  - Fires NM info notification: "EV force-charge window opened until HH:MM. Mid-peak rates apply."
  - Auto-expires after 30 min; URA resumes pausing on the next tick after expiry
- **Override state visible:**
  - `switch.ura_energy_coordinator_ev_tou_management` gains an `override_active_until_iso` attribute
  - When override active, the switch's friendly state implicitly carries that information (no separate sensor)
- **Idempotent:** pressing the button while an override is already active extends the window by another 30 min from press time (not additive — replaces)
- **No HA-side bypass:** the override ONLY engages via the URA button. HA-side EVSE switch manipulation alone does NOT bypass URA's pause (D1 enforces this).

**Why not a switch entity?** A switch is too casual — HA UI tap is one finger swipe. A button + log entry + NM notification is the "deliberate action" pattern. Auditable.

**Future enhancement (out of scope here):** a longer-duration button (`force_charge_2h`) or a configurable duration via options flow. Defer until 30-min default proves insufficient.

**Acceptance criteria:**
- **Verify:** Press button during mid-peak → EV TOU pause skipped for 30 min; NM notification fires; `switch.ura_energy_coordinator_ev_tou_management.attributes.override_active_until_iso` populated
- **Verify:** 30 min later → override auto-expires; next decision cycle re-pauses EVSE
- **Verify:** Press button again while override active → extends another 30 min from now (replaces, not stacks)
- **Test:** `test_force_charge_button_opens_30min_window`, `test_force_charge_auto_expires`, `test_force_charge_re_press_extends`, `test_no_ha_side_bypass_when_no_override_active`
- **Live:** Press button during mid-peak; observe NM message + EV starts charging; ~30 min later EV pauses again

### D4 — Energy situation visibility enrichment (no new entities)

**File:** `sensor.py` (existing `EnergyBatteryStrategySensor` class, the `_attr_extra_state_attributes` shape)
**Effort:** ~30 LoC + 1 test
**Bug class prevention:** #29 (populator coverage), #32 (no orphan form fields)

**Per user's "(too much?)" concern about adding new sensors: NO new entities. Enrich existing attributes only.**

`sensor.ura_energy_coordinator_battery_strategy` gains these attributes:

| Attribute | Value | Example |
|---|---|---|
| `optimization_summary` | One-sentence plain English of current strategy | `"Holding battery at 88% because EV is charging. Grid covers ~11 kW at $0.13/kWh (~$1.45/hr)."` |
| `current_grid_cost_per_hour` | Live $/hr burn rate from current import | `1.45` |
| `next_decision_boundary` | What changes next + when | `{"event": "off_peak_starts", "in_minutes": 124, "expected_action": "battery will drain toward 10% target"}` |
| `current_holds_active` | List of holds preventing normal drain | `["evse_battery_hold"]` or `[]` |
| `evse_force_charge_until_iso` | If admin override active, when it expires | `"2026-05-28T01:30:00-05:00"` or `null` |

PWA Dashboard's Energy tab can render these in a "What URA is doing" panel without any backend changes. Documented in the PWA brief.

**Acceptance criteria:**
- **Verify:** During EVSE hold → `optimization_summary` mentions the hold; `current_holds_active` includes `"evse_battery_hold"`
- **Verify:** During normal drain → summary reflects "discharging to cover load"; holds list empty
- **Test:** `test_optimization_summary_during_evse_hold`, `test_optimization_summary_during_normal_drain`, `test_next_decision_boundary_calculation`
- **Live:** Observe attribute updates within one decision cycle of state changes

### D5 — Documentation updates

- `docs/user-manual/ENERGY_COORDINATOR.md` — update §3 (kill-switches) with the EV TOU strict-policy behavior; add new §X for the admin override button + its semantics
- `docs/ENERGY_MANAGEMENT_EXPLAINER.md` — add brief note in §6a (Grid Import Cap) about the parallel "EV TOU policy is mandate, override via URA button only" model
- `docs/QUALITY_CONTEXT.md` — propose new bug class candidate: "Bookkeeping short-circuit defeated by external state change" (or similar) — D1's class of bug. Confirm with reviewer before adding.

---

## Tier 2 Review Framings (2 parallel)

- **Reviewer A — Correctness + EC startup race.** D1: strict re-pause idempotency + excess-solar exception preserved. D2: deferred-restore replacement covers all observed boot-timeline scenarios. D3: override button state machine (30-min window, idempotent re-press, auto-expiry). Bug class #5, #10, #21, #23, #38.
- **Reviewer B — Async lifecycle + cross-coordinator.** D2: event-driven retry handles HA restart mid-incident; SIGNAL_ENERGY_COORDINATOR_READY dispatcher lifecycle. D3: NM notification dispatch through observation-mode gate. D4: attribute computation never blocks (no DB queries on sensor read). Bug class #19, #28, #42 (no lambda+async_create_task patterns introduced).

---

## Live Validation (Review C — post-deploy)

1. **D1 strict re-pause:** force a manual override during mid-peak; observe URA repause within one decision cycle. Repeat 3x; URA never gives up.
2. **D2 sub-switch state restore:** disable Envoy briefly to force EC validation skip; re-enable; all 5 sub-switches recover to saved values within 60s of EC re-init. `binary_sensor.ura_energy_coordinator_sub_switches_synced` transitions False → True.
3. **D3 admin override:** press `button.ura_energy_coordinator_evse_force_charge_30min`; verify NM notification, override-until attribute, EV un-paused. Wait 30 min; verify auto-expiry and EV re-paused.
4. **D4 visibility:** check `sensor.ura_energy_coordinator_battery_strategy.attributes` for `optimization_summary` and `current_holds_active` reflecting reality across 3-4 state transitions.

---

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| D1's strict re-pause could fight legit user actions during off-peak edge cases | D1 only acts during peak + mid_peak; off-peak is untouched. Excess-solar exception preserved. |
| D2's event-driven retry could itself become an untracked-task source | Use single `async_dispatcher_connect` per switch; tracked via `async_on_remove`. No `async_create_task` loops. Bug class #19 prevention checklist. |
| D3 override button accidentally activated | Single-press = 30 min only. NM notification fires loudly. Audit log in DB. Future enhancement: confirmation modal in PWA. |
| D4 attribute computation slowing decision cycle | All computation is constant-time over already-loaded state. No DB queries from sensor reads. |

---

## File touch list

- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py` — D1 strict re-pause (~10 LoC)
- `custom_components/universal_room_automation/switch.py` — D2 sub-switch state restore (~50-80 LoC)
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — D2 SIGNAL_ENERGY_COORDINATOR_READY emit + D3 override window state machine (~30-50 LoC)
- `custom_components/universal_room_automation/button.py` — D3 new `EVSEForceChargeButton` (~30 LoC)
- `custom_components/universal_room_automation/sensor.py` — D2 new `EVSyncedBinarySensor` + D4 attribute enrichment on `EnergyBatteryStrategySensor` (~60 LoC)
- `custom_components/universal_room_automation/domain_coordinators/signals.py` — new `SIGNAL_ENERGY_COORDINATOR_READY` (~5 LoC)
- `quality/tests/test_v47x_ev_tou_hardening.py` — NEW (~350 LoC)
- `docs/user-manual/ENERGY_COORDINATOR.md` + `docs/ENERGY_MANAGEMENT_EXPLAINER.md` — updates (~30 LoC)

**Estimated totals:** ~200-250 prod LoC + ~350 test LoC across ~7 files.

---

## Acceptance criteria summary

Release "done" when:
- All v4.7.x tests pass; isolation check 0 failures
- Tier 2 review docs filed; CRITICAL/HIGH fixed
- Live validation §3 above passes on user's HA
- All 5 EC sub-switches reliably restore to saved values across simulated Envoy outages
- EV TOU re-pause demonstrably defeats manual HA-side override within 5 min
- Force-charge button opens 30-min override window; NM notification fires; auto-expires
- `sensor.ura_energy_coordinator_battery_strategy.attributes.optimization_summary` populates in plain English

---

## Cross-references

- Triggers: 2026-05-27 live diagnostic showing EV TOU off + EVSE charging at mid-peak
- Predecessor: `memory/project_ec_startup_race_evidence.md` — this cycle ships the resilience code that memory was waiting on
- Sibling: Dynamic Preset Management Cycle B (independent timeline; can ship in either order)
