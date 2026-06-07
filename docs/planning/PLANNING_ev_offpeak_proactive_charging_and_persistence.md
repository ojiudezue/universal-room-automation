# PLANNING — EV Off-Peak Proactive Charging + Pause-State Persistence Hardening

**Status:** Tier 2-DB feature cycle — planning only. **No build, no deploy.**
**Filename has no version number per URA convention** (versioning assigned at deploy time).
**Authoring date:** 2026-06-07
**Cycle shape:** WS1 (persistence hardening) sequenced before WS2 (behavior change). Single deploy.

---

## 1. Why this cycle exists

The EV charging subsystem is good at PAUSING but bad at persistently STARTING. The car has not been charged by morning for weeks. Three failure modes share the same root cause:

1. **Evening excess-solar turn-off gap.** When solar collapse drops `_excess_solar_active`, the EVSE is turned off (`energy_pool.py:628-642`). Nothing re-initiates the charge once off-peak begins at 21:00 because the off-peak branch of `determine_actions` (`energy_pool.py:469-489`) only turns a charger ON if `evse_id in self._paused_by_us` — a resume-my-own-pause rule, not an initiator.
2. **Fresh plug-in overnight.** A car plugged in at 22:00 was never in `_paused_by_us`, so the off-peak branch silently no-ops. The only proactive turn-ON in the system, `determine_excess_solar_actions` (`energy_pool.py:536-644`), is gated on `soc >= 95 AND remaining_forecast_kwh >= 5.0` (`:569-574`) — a daytime-solar rule that cannot fire overnight.
3. **Post-restart.** In-memory pause sets clear on restart. `_paused_by_us` + `_excess_solar_active` are restored from the `evse_state` DB table (`energy.py:858-904`); `_paused_by_grid_cap` + `_paused_by_battery_drain` are restored from the `energy_state` KV store (`energy.py:876-894`). **But `_paused_by_fill_priority` and `_paused_by_arbitrage` are NOT persisted at all** (no save calls in `energy.py` — verified by grep), and `_force_charge_until` is persisted only via the Switch RestoreEntity attribute (`switch.py:802-854`) which uses `datetime.fromisoformat` rather than `dt_util.parse_datetime` (Bug Class #13/#21 risk).

The behavior fix is small: turn the off-peak branch from a resume-only rule into an *ensure-on* rule that respects existing pause-precedence. The persistence work is small: close the remaining gaps using the existing `energy_state` KV pattern. Both must ship together because the new intent state ("URA decided to keep the EVSE on overnight") does not auto-re-derive, so it must survive restart on day one.

---

## 2. Institutional context verified

This section is the proof-of-work that the planner consulted prior art before scoping changes. Per CLAUDE.md, reviewers verify it during the review pass.

### 2.1 Greps run + results — REUSED vs NEW

| Proposed surface | Verdict | Evidence |
|---|---|---|
| TOU toggle (gates new behavior) | **REUSED** `_ev_tou_enabled` at `energy.py:252` (init), `energy.py:2184` (gates `determine_actions`), `energy.py:2288` (gates L1 plug TOU), `energy.py:3759-3765` (property + setter). Backed by `ECEvTouSwitch` (`switch.py:773`) with RestoreEntity persistence already in place. | Grep `_ev_tou_enabled\|ev_tou_enabled\|EV_TOU` → 10 hits, all in `energy.py` / `switch.py`. Operator instruction: "build into current toggles." |
| Excess-solar enable gate | **REUSED** `_excess_solar_enabled` (`energy.py:2206`, `energy.py:2252`). Not relevant to off-peak proactive turn-on — listed only to confirm we do NOT need to widen its scope. | Grep `_excess_solar_enabled` → unchanged. |
| Force-charge admin window state | **REUSED** `_force_charge_until` (`energy_pool.py:214`) + `set_force_charge_override` (`energy_pool.py:525-534`) + Switch-attribute restore (`switch.py:802-854`). **NEW (small):** mirror the same value into the existing `energy_state` KV store with a key like `ev_force_charge_until` so a clean force-charge restart works even if the Switch entity load order or attribute serialization breaks. The Switch path stays as a fast-path; KV is the durable canonical. |
| Fill-priority pause persistence | **NEW** key `ev_fill_priority_paused` in the existing `energy_state` KV store. Mirrors the verified pattern at `energy.py:919-927` for `evse_grid_cap_paused` + `evse_battery_drain_paused`. **No new table, no schema change.** |
| Arbitrage pause persistence | **NEW** key `ev_arbitrage_paused` in `energy_state` KV (same pattern). **DEFERRED — see Plan Completion Tracking § 9.** Arbitrage re-derives from `decision["arbitrage_phase"]` on the next tick (`energy.py:2194-2203`), so the restart cost is at most one cycle of incorrect "EVSE held by arbitrage" attribution. Mention but do not build. |
| Staleness guard on `restore_evse_state` | **NEW** but localized to `database.py:3682`. The `updated_at` column already exists and is written (`database.py:3676`). Add a `max_age` parameter (default ~10 hours = wider than one TOU off-peak window so a normal overnight outage still restores; tighter than 24h so a multi-day outage doesn't re-seed wrong intent). Same pattern as the existing 4h envoy cache staleness guard (`energy.py:_restore_envoy_cache` — found via `_restore_envoy_cache` grep). |
| New CONF_* in `const.py` | **NONE.** Confirmed via grep `CONF_EV_TOU\|CONF_EV_OFFPEAK\|CONF_OFFPEAK_PROACTIVE\|offpeak_proactive\|proactive_charging` → 0 hits. The TOU toggle widens semantics; no new config surface. |
| New table | **NONE.** `evse_state` (`database.py:874`) handles per-EVSE booleans; `energy_state` (`database.py:939`) handles JSON KV. Both are sufficient. |
| New sensor | **NONE** in the strict sense. The existing `evse_force_charge_until_iso` attribute (`sensor.py:6571`, `sensor.py:6714`) already surfaces the override expiry. We will ADD a small `proactive_offpeak_holds` attribute to the EV status sensor listing which EVSEs are currently being held on by the new rule — see D4 acceptance criteria. |
| Observation-mode gate | **REUSED** `_observation_mode` (`energy.py:395`, gate at `energy.py:2174`). The `determine_actions` block is already inside `if not self._observation_mode:` — the new branch inherits the gate at no additional code. Verify in review C. |

### 2.2 Prior planning docs consulted

- `docs/planning/PLANNING_v4.7.6_evse_solar_aware_charging.md` — fill-priority pause design (`_paused_by_fill_priority` was new in v4.7.6).
- `docs/planning/PLANNING_v4.7.x_advanced_energy_management.md` — broader EV/battery context.
- `docs/planning/PLANNING_v4.7.6.1_labels_helpers_excess_solar_number.md` — fill-priority knob exposure (Number entities).
- (Skimmed) `PLANNING_v4.7.4_dpm_ui_simplification.md`, `PLANNING_v4.7.7_ac_nudge_decouple_plus_dpm_sensor_cleanup.md` — DPM-side cycles, not relevant; confirmed they did not touch EV control paths.

### 2.3 Memory bodies pulled

- `feedback_db_sensitive_3x_targeted_reviews.md` — Tier 2-DB rationale; three framings must not share blind spots.
- `feedback_pre_deploy_zero_bugs_gate.md` — applies at deploy time, not in this plan.
- `feedback_fix_lows_in_cycle.md` — LOWs fixed in the same fix-up pass as MEDIUMs; not deferred to a follow-up cycle.
- `feedback_parsimonious_room_config.md` — applies tangentially: we add zero new room-level config, in line with the principle.
- `project_v476_live.md` — v4.7.6 was the original EVSE-solar Tier 2-DB cycle; same EV controller, same pause sets. Confirms three-reviewer protocol is the right shape for EV pause-set changes.

### 2.4 Design docs read

- `docs/Coordinator/Energy.md` — coordinator-level design doc. Reread for context on the decision-cycle ordering invariants (TOU → arbitrage → excess_solar → grid_cap → drain → fill_priority).
- (No HVAC/Presence/Safety docs relevant.)

### 2.5 Code locations surveyed end-to-end

- `domain_coordinators/energy_pool.py` lines 1-700 (EV controller class — `determine_actions`, `determine_excess_solar_actions`, `_is_force_charge_active`, `set_force_charge_override`, the pause-tracking helpers).
- `domain_coordinators/energy.py` lines 240-260 (init), 760-930 (restore + save), 2170-2300 (decision-cycle ordering), 2420-2440 (`_periodic_db_writes` cadence), 3530-3550 (the writes themselves), 3700-3730 (`async_teardown`), 3755-3770 (TOU toggle property), 3935-4015 (fill-priority edge-detect / NM trip).
- `domain_coordinators/energy_const.py` lines 1-60 (TOU windows — summer off-peak `[(0,14),(21,24)]`, mid_peak `[(14,16),(20,21)]`, peak `[(16,20)]`).
- `database.py` lines 860-945 (`evse_state` + `energy_state` schemas), 3640-3700 (EVSE DAOs), 3960-4000 (`save_energy_state` / `restore_energy_state`).
- `switch.py` lines 770-900 (`ECEvTouSwitch` — restore + override re-application).
- `button.py` lines 1380-1440 (`EVSEForceChargeButton` — admin path).
- `sensor.py` lines 6560-6720 (EV status sensor attribute surface).

### 2.6 What we did NOT read and why

- `presence.py`, `hvac.py`, `safety.py` — not touched. Confirmed by reviewing the proposed deliverables; no cross-coordinator wiring.
- `config_flow.py`, `options_flow.py` — no new CONF_* added (verified by grep), so config flows are out of scope.

---

## 3. Tier classification — TIER 2-DB

**Why Tier 2-DB and not Tier 2:**

- WS1 changes the `restore_evse_state` DAO signature (adds `max_age` parameter), touching every existing caller.
- WS1 changes the payload shape persisted under `energy_state` (new keys; ISO string for `_force_charge_until`).
- WS1 + WS2 together change the *meaning* of an existing toggle (`_ev_tou_enabled`) and the *behavior* of the only `determine_actions` codepath that drives EV switches outside excess-solar conditions.
- A regression here either (a) silently fails to charge the car overnight (current state — already a months-long incident), or (b) over-charges by failing to respect a battery-drain or fill-priority guard, costing the home battery's overnight reserve.
- The three-framings discipline applies: persistence correctness, precedence-chain integrity, and toggle-semantics change cover non-overlapping blind spots. A single reviewer pass would defensibly miss one of the three.

Operator may also elevate to Tier 2-DB on trust-hierarchy grounds (EV ↔ battery ↔ TOU ↔ guard sets ripple); documenting that here so reviewers know the bar.

---

## 4. Workstream 1 — Persistence hardening (sequence first)

WS1 closes gaps so WS2's new intent-state (proactive off-peak hold) survives a restart on day one. All persistence uses the EXISTING `energy_state` KV store and EXISTING `evse_state` table — no schema migration.

### D1.1 — Persist `_force_charge_until` to `energy_state` KV (canonical durable copy)

**What:** Mirror the in-memory `_force_charge_until` (`energy_pool.py:214`) into a new key `ev_force_charge_until` in the existing `energy_state` KV store. Value = ISO string with timezone info from `dt_util.now().isoformat()` (Bug Class #21). On restore, use `dt_util.parse_datetime()` (NOT `datetime.fromisoformat()` — Bug Class #13/#21). If the parsed value is None or already expired vs `dt_util.utcnow()`, drop it silently (built-in staleness guard).

**Where:**
- Save: extend `_save_evse_state` (`energy.py:906-929`) to also write `ev_force_charge_until`. Reuse the existing 15-min cadence + teardown call site — no new timer (Bug Class #19/#42 — no untracked fire-and-forget tasks).
- Restore: extend `_restore_evse_state` (`energy.py:858-904`) to also read `ev_force_charge_until` and call `self._ev.set_force_charge_override(parsed_until)` if the value is in the future. Position the call AFTER the existing pause-set restores so observation-mode bookkeeping (which restore_evse_state already does) is intact.
- Switch RestoreEntity path at `switch.py:802-854` STAYS as a fast-path for entity-attribute round-trip. On any conflict between Switch-attribute and KV, the KV value wins (KV is canonical). The reason for keeping the Switch path: it survives a DB write failure during the prior shutdown.

**Why not just rely on Switch RestoreEntity:** the Switch path uses `datetime.fromisoformat()` (Bug Class #13/#21 — naive datetime risk), depends on entity attribute serialization which has historically had quirks, and bypasses the centralized save cadence. KV is the canonical save; Switch is the fast-path. Both pointing at the same source of truth means the WS2 behavior change is durable on day one.

**Bug classes honored:**
- **#10** — cross-restart loss closed.
- **#13/#21** — restore uses `dt_util.parse_datetime`; save uses `dt_util.now().isoformat()` to guarantee tz-aware.
- **#43** — does not introduce new bookkeeping short-circuits.

#### Acceptance Criteria — D1.1
- **Verify:** Pressing the EVSEForceChargeButton, then immediately killing HA and restarting, the override window persists across restart and the EVSE is not paused by TOU during the remaining force-charge window.
- **Sensor:** `sensor.ura_energy_coordinator_ev_status` shows `evse_force_charge_until_iso` populated with the original ISO string (within 1-min tolerance) post-restart.
- **Test:** New unit test `test_force_charge_until_round_trip_kv` in `quality/tests/test_ev_offpeak_proactive.py`:
  - Set override, call `_save_evse_state`, clear in-memory state, call `_restore_evse_state`, assert `_force_charge_until` is the original UTC-aware datetime.
  - Set override in the past, call save then restore, assert `_force_charge_until is None` (built-in staleness).
  - Save with `datetime.now()` (naive), restore — assert behavior is correct, not a `TypeError`.
- **Test:** AST test that `_restore_evse_state` does not call `datetime.fromisoformat` directly (must go through `dt_util.parse_datetime`).
- **Live:** Set a 30-min override at 21:05, run `mcp ura-sqlite` query `SELECT value FROM energy_state WHERE key='ev_force_charge_until'` — value is an ISO string with timezone. Restart HA. Re-query — value still present until `dt_util.utcnow()` passes the expiry, then cleared on the first tick post-expiry.

---

### D1.2 — Persist `_paused_by_fill_priority` to `energy_state` KV

**What:** Mirror the `evse_grid_cap_paused` + `evse_battery_drain_paused` pattern (`energy.py:919-927`) for the fill-priority pause set. New key: `evse_fill_priority_paused`. Value: JSON list of EVSE IDs. Save + restore are exact analogues of the existing grid-cap path — no new code shape, just new key.

**Where:**
- Save: `_save_evse_state` (`energy.py:906-929`) — add one more `await db.save_energy_state("evse_fill_priority_paused", _json.dumps(list(self._ev._paused_by_fill_priority)))` call after the existing two.
- Restore: `_restore_evse_state` (`energy.py:858-904`) — add one more `restore_energy_state("evse_fill_priority_paused")` block after the existing two, filtering against `valid_evse_ids` and the new `max_age` guard (D1.4).

**Why fill-priority and not arbitrage:** arbitrage re-derives from `decision["arbitrage_phase"]` on the next tick (`energy.py:2194-2203`), so a restart costs at most one cycle of misattribution. Fill-priority is computed from SOC + forecast + threshold — the re-evaluation can flap if the same conditions cross the threshold during restart settle. Persisting it gives a stable handoff. (Arbitrage persistence is listed in § 9 Plan Completion Tracking as a future-work item.)

**Bug classes honored:**
- **#10** — cross-restart loss closed.
- **#25** — no DELETE introduced; uses INSERT OR REPLACE (already in `save_energy_state`).
- **#26** — save cadence is the existing 15-min `_periodic_db_writes`; no per-tick DB hit.

#### Acceptance Criteria — D1.2
- **Verify:** When the fill-priority rule pauses an EVSE and HA restarts within 15 min, the EVSE remains in `_paused_by_fill_priority` after restart (visible via debug log on first decision cycle).
- **Sensor:** EV status sensor attribute `fill_priority_paused_evses` (or equivalent existing surface — verify in build) lists the EVSE post-restart.
- **Test:** Unit test `test_fill_priority_paused_round_trip` — populate set, save, clear, restore, assert membership.
- **Test:** Stale-EVSE-ID filter test — KV row contains an EVSE ID not in `self._ev._evse`; on restore, that ID is dropped (mirrors the existing `valid_evse_ids` filter for `evse_grid_cap_paused`).
- **Live:** Force a fill-priority pause (e.g., temporarily set fill-priority SOC threshold above current battery SOC during sun-up), wait for save tick, restart HA, re-query DB and assert the EVSE is still in the set post-restart for the duration that the rule still applies.

---

### D1.3 — Persist new `_proactive_offpeak_holds` set (WS2's new intent-state)

**What:** WS2 (§ 5) introduces a new bookkeeping set `_proactive_offpeak_holds: set[str]` in `EVChargerController` (`energy_pool.py`) that records EVSEs URA is *actively keeping on* during off-peak. This is the intent-state that does NOT re-derive — if the user manually turns the EVSE off mid-off-peak, the set must remember "URA intended on" so the next tick re-enforces. Persist this set in the existing `energy_state` KV under key `evse_proactive_offpeak_holds`. Same JSON-list pattern as D1.2.

**Where:**
- Init: `EVChargerController.__init__` (`energy_pool.py` around `:214`) — `self._proactive_offpeak_holds: set[str] = set()`. Prune in `_prune_removed_evses` (`energy_pool.py:369-401`) alongside the other pause sets.
- Save: extend `_save_evse_state` (`energy.py:906-929`) with one more `save_energy_state` call.
- Restore: extend `_restore_evse_state` (`energy.py:858-904`) with one more `restore_energy_state` block.

**Why a new set rather than reusing `_paused_by_us`:** `_paused_by_us` means "we paused this." Overloading it to also mean "we ensured-on this" would defeat its existing role in the resume-precedence checks at `energy_pool.py:471-481` (which read "was this paused by us"). A separate set keeps the existing semantics intact and makes the new behavior auditable.

**Bug classes honored:**
- **#10**, **#43** — explicit intent-state survives restart AND survives manual user re-enable/disable.

#### Acceptance Criteria — D1.3
- **Verify:** When WS2 turns an EVSE on during off-peak, the EVSE ID appears in `_proactive_offpeak_holds`. After HA restart within the off-peak window, the set is repopulated from DB and the EVSE remains on (no off→on flap on first post-restart tick).
- **Sensor:** EV status sensor attribute `proactive_offpeak_holds` (new attribute — D4) lists current member EVSE IDs.
- **Test:** Round-trip unit test. Same shape as D1.2.
- **Test:** Stale-EVSE-ID filter test.
- **Live:** Confirm `mcp ura-sqlite` query `SELECT value FROM energy_state WHERE key='evse_proactive_offpeak_holds'` returns a non-empty JSON list during off-peak with at least one EVSE plugged in. Restart HA inside off-peak — the EVSE stays on through the restart and the KV row is restored.

---

### D1.4 — `restore_evse_state` staleness guard

**What:** Add a `max_age_hours: float | None = 10.0` parameter to `database.py:restore_evse_state` (`database.py:3682-3699`). Default 10h chosen because it is wider than one summer off-peak window (`[(0,14)]` = 14h is too wide for safe stale re-seed; `[(21,24)]` = 3h is too narrow to survive an evening outage; 10h covers a normal overnight HA outage but rejects a multi-day power outage). Filter rows whose `updated_at` is older than `max_age_hours` before the dt_util cutoff. Skipped rows are logged at INFO ("EVSE state row %s older than %sh — skipping restore").

Apply the same `max_age` guard to the new energy_state KV reads inside `_restore_evse_state` — but route via a small helper `_restore_kv_with_age(key, max_age_hours)` that reads the `updated_at` column on `energy_state` (already written by `save_energy_state` at `database.py:3971`).

**Where:**
- `database.py:3682` — `restore_evse_state` signature change.
- `database.py:3981` — `restore_energy_state` — consider adding `max_age_hours` parameter OR add a sibling DAO `restore_energy_state_with_age` that returns `(value, updated_at)` so the caller decides. Pick whichever is closer to the existing idiom; lean toward the sibling DAO so existing callers do not need migration.
- `energy.py:858-904` — `_restore_evse_state` passes `max_age_hours=10.0` to all DAO calls.

**Why 10h and not 24h:** Operator runs HA on Home Assistant Yellow; typical restart cycles are 5-15 min, planned outages rarely exceed 4-6h. A 24h+ outage is a deployment incident, not an EV-charging event, and stale pause-state from "yesterday" should not steer today's decisions.

**Bug classes honored:**
- **#10** — restore is bounded; long outage does not reseed stale state.
- **#13/#21** — `updated_at` is parsed via `dt_util.parse_datetime`, not `datetime.fromisoformat`.
- **#25** — no DELETE in the read path. Stale rows are simply ignored on read; pruning belongs to nightly maintenance (not in this cycle).
- **#26** — staleness check is a row-by-row Python comparison after the DB SELECT; no extra DB round-trip.

#### Acceptance Criteria — D1.4
- **Verify:** Hand-inject an EVSE state row with `updated_at` = 12h ago; restart HA; the row is NOT applied to in-memory state.
- **Verify:** Hand-inject the same row with `updated_at` = 8h ago; row IS applied.
- **Sensor:** No new sensor; log scan via `ha_get_logs(search="older than")` shows the staleness warning for the 12h case.
- **Test:** Unit tests `test_restore_evse_state_stale_skipped` + `test_restore_evse_state_fresh_applied` covering both branches.
- **Live:** Stop HA, manually `UPDATE evse_state SET updated_at = datetime('now', '-12 hours')` for one EVSE row, restart HA, confirm via debug log + EV status sensor attribute that the EVSE is not in `_paused_by_us` after restart.

---

## 5. Workstream 2 — Proactive off-peak charging behavior change

WS2 changes the off-peak branch of `EVChargerController.determine_actions` (`energy_pool.py:469-489`) from *resume-only* to *ensure-on with guard precedence*. It is the smallest possible code change consistent with the precedence-chain invariant established in v4.7.6.

### D2.1 — Off-peak ensure-on with precedence pre-check

**What:** Replace the existing off-peak branch (`energy_pool.py:469-489`) with logic that:

1. For each configured EVSE:
2. If `evse_id in self._paused_by_battery_drain` OR `_paused_by_fill_priority` OR `_paused_by_grid_cap` OR `_paused_by_arbitrage`: skip (do nothing). The downstream guard rules (`energy.py:2241`, `2255`, `2224`, `2198`) will continue to handle re-pause; we must not pre-empt them.
3. If `force_charge_active` was already detected at the top of `determine_actions` (`energy_pool.py:431-437`): skip (force-charge is its own escape hatch — D2.4).
4. If `state["is_on"]` is True: ensure `evse_id` is in `_proactive_offpeak_holds`, then continue. (Already on; just claim the hold.)
5. If `state["is_on"]` is False: dispatch `switch.turn_on`, add to `_proactive_offpeak_holds`. If the EVSE was in `_paused_by_us` (TOU resume case), discard from `_paused_by_us` (matches current semantics).
6. Outside the off-peak branch: when the period exits off-peak (peak / mid_peak), the existing peak-branch authoritative re-pause already covers turning off EVSEs that are still in `_proactive_offpeak_holds`. Add a clean-up: on transition out of off-peak, clear `_proactive_offpeak_holds` for EVSEs we are pausing.

**Code shape (illustrative, not authoritative for the builder):**

```python
else:  # off-peak branch (tou_period not in peak/mid_peak)
    # Carry-over guards win (battery protections override TOU intent).
    if (evse_id in self._paused_by_battery_drain
            or evse_id in self._paused_by_fill_priority
            or evse_id in self._paused_by_grid_cap
            or evse_id in self._paused_by_arbitrage):
        # Drop legacy TOU bookkeeping; guard rules will keep the EVSE off.
        self._paused_by_us.discard(evse_id)
        self._proactive_offpeak_holds.discard(evse_id)
        continue
    if force_charge_active:
        # Force-charge already authorizes on; don't double-claim here.
        continue
    if not state["is_on"]:
        actions.append({
            "service": "switch.turn_on",
            "target": switch_entity,
            "data": {},
        })
        _LOGGER.info("EV: proactive off-peak turn-on for %s", evse_id)
    self._proactive_offpeak_holds.add(evse_id)
    self._paused_by_us.discard(evse_id)
```

**Decision-cycle ordering verified:** `determine_actions` runs at `energy.py:2185`. Subsequent guards run at `energy.py:2198` (arbitrage), `:2211` (excess_solar), `:2224` (grid_cap), `:2241` (drain), `:2255` (fill_priority). The carry-over guard sets read at step 2 above are the *previous tick's* values; a guard that needs to fire NEWLY this tick (e.g. drain just tripped) will be evaluated after `determine_actions` and re-pause the EVSE — but D2.1's pre-check prevents the visible on→off flap in the common case where a guard set is non-empty entering this tick.

**Flap-prevention edge case:** if a guard set is empty entering this tick (so D2.1 turns on), but the guard rule fires NEWLY this tick (e.g. drain crosses threshold), the visible result is an on-then-off in a single decision cycle. This is acceptable — the guards already permit this behavior today on the analogous excess-solar path (`energy_pool.py:610-621` then drain at `energy.py:2241`). Document this in the code comment so future reviewers don't think it's a bug.

**Toggle reuse decision:**

The operator instructed "build into current toggles." This widens `_ev_tou_enabled` (gates the whole `determine_actions` call at `energy.py:2184`) from "pause in peak" to "pause in peak + ensure-on in off-peak."

**Alternatives weighed for completeness:**

- **Option A — Reuse `_ev_tou_enabled` (RECOMMENDED, operator preference).** Zero new config surface. Honors `feedback_parsimonious_room_config.md`. Cost: semantics change for an existing user-visible toggle; if the user only wants pause-in-peak they get ensure-on-in-off-peak forced too. Release note must be loud.
- **Option B — Add a new sub-toggle `ev_offpeak_proactive_enabled` (rejected).** Cleaner semantics but adds a Switch entity + RestoreEntity for a behavior most users will leave default-on. The complexity cost exceeds the user-control benefit, and the operator's lean is explicit. Listed only as a contingency if review B flags the semantics change as a deal-breaker.

**Recommendation: ship Option A. If review B's reviewer disagrees, fall back to Option B in fix-up with a +30 LoC scope add.**

**Bug classes honored:**
- **#23 (observation mode)** — the new branch sits inside `if not self._observation_mode:` at `energy.py:2174`. Verify no new code path bypasses this gate. (Confirmed by reading the call site; this is a no-op for the planner but a required reviewer check in framing C.)
- **#43 (bookkeeping short-circuit defeated by external state)** — this is the bug class we are fixing. The new branch does NOT add a "if already in `_proactive_offpeak_holds` skip" guard; it re-issues `turn_on` every tick if the user has turned the switch off manually, matching the v4.7.x D1 idempotent-re-pause philosophy on the peak side. Operator's `self_modulates` escape hatch (`energy_pool.py:309-320`) and the force-charge button remain for legitimate bypasses.
- **#42 (lambda + async_create_task)** — no new lambdas in scheduler callbacks. The decision-cycle timer is the existing one.
- **#19 (untracked background tasks)** — no new `hass.async_create_task` calls.
- **#25/#26** — no new DB DELETE; no per-tick DB read.

#### Acceptance Criteria — D2.1
- **Verify (off-peak fresh plug-in):** Plug an EVSE into a switch that is OFF, during off-peak, with no guards active. Within one decision cycle (≤5 min), URA dispatches `switch.turn_on`. The EVSE remains on for the duration of off-peak (excluding new guard trips).
- **Verify (evening excess-solar handoff):** During the 20:00→21:00 transition where excess-solar turns off the EVSE at sundown, then off-peak begins at 21:00. The EVSE is re-enabled on the first off-peak decision cycle.
- **Verify (battery-drain still wins):** Force battery drain conditions during off-peak. The EVSE turns on at `determine_actions` step, then the drain rule turns it off in the same tick. The EVSE ends the tick OFF. `_proactive_offpeak_holds` is cleared for that EVSE. Net visible behavior: stays off.
- **Verify (fill-priority still wins):** Same as above for fill-priority. EVSE held off; `_proactive_offpeak_holds` cleared.
- **Verify (manual user re-disable):** User turns the EVSE off in HA mid-off-peak. On the next decision cycle, URA re-issues `turn_on` (idempotent enforcement). Cost: matches the peak-side idempotent re-pause philosophy in v4.7.x D1.
- **Verify (self_modulates EVSE):** EVSE configured with `self_modulates: true`. The proactive turn-on still fires (the `self_modulates` flag governs manual-override detection in the pause path, not the enforcement path). Confirm via a planner-builder note: this is the intended behavior; if the operator wants self-modulating EVSEs to ALSO opt out of proactive-on, that is a separate config knob (see § 9).
- **Verify (toggle off):** With `switch.ura_energy_coordinator_ev_tou_management` off, NO proactive turn-on fires. The toggle still gates the whole `determine_actions` call.
- **Verify (observation mode):** With observation mode on, NO proactive turn-on fires (gated by the existing `if not self._observation_mode:` at `energy.py:2174`).
- **Sensor:** EV status sensor (`sensor.ura_energy_coordinator_ev_status`) gains attribute `proactive_offpeak_holds` listing current EVSE IDs (D4).
- **Test:** Unit tests in `quality/tests/test_ev_offpeak_proactive.py` covering each Verify scenario above:
  - `test_offpeak_fresh_plug_in_turns_on`
  - `test_offpeak_handoff_from_excess_solar`
  - `test_battery_drain_carryover_blocks_proactive_on`
  - `test_fill_priority_carryover_blocks_proactive_on`
  - `test_grid_cap_carryover_blocks_proactive_on`
  - `test_arbitrage_carryover_blocks_proactive_on`
  - `test_manual_user_disable_reenforced_next_tick`
  - `test_tou_toggle_off_disables_proactive_on`
  - `test_observation_mode_blocks_proactive_on`
  - `test_force_charge_active_skips_proactive_on` (force-charge already authorizes; redundant claim avoided)
  - `test_peak_transition_clears_proactive_offpeak_holds`
- **Live:** Plug EVSE in at 21:30 (off-peak in summer schedule), confirm via `ha_states get switch.<evse>` that state is `on` within 5 min; confirm sensor attribute `proactive_offpeak_holds` includes that EVSE; confirm `mcp ura-sqlite` query on the EVSE's power-history table shows non-zero kW during off-peak.

---

### D2.2 — Transition-out cleanup

**What:** When `tou_period` enters `peak` or `mid_peak`, the existing peak branch (`energy_pool.py:446-468`) already issues `switch.turn_off` for any EVSE that is `is_on`. Extend that branch to also `discard` the EVSE from `_proactive_offpeak_holds` so the bookkeeping does not stale-carry into the next off-peak window. Same for the excess-solar peak-clear (`energy_pool.py:553-567`).

**Why:** Without this, `_proactive_offpeak_holds` would accumulate forever, and a subsequent off-peak re-entry would see a non-empty set referencing EVSEs that may have been disconnected hours ago. The `_prune_removed_evses` path catches config removal, but does not catch transient unplug.

**Bug classes honored:** #43 — keeps the bookkeeping set in sync with the actual policy state.

#### Acceptance Criteria — D2.2
- **Verify:** Charge an EVSE during off-peak (D2.1). At 16:00 (peak start), URA turns the EVSE off. `_proactive_offpeak_holds` no longer contains the EVSE.
- **Test:** `test_peak_transition_clears_proactive_offpeak_holds` (already listed in D2.1) — assert set is empty after a `determine_actions(period="peak")` call following a series of `determine_actions(period="off_peak")` calls.
- **Live:** Observe EV status sensor attribute `proactive_offpeak_holds` shrink to `[]` at 16:00 transition.

---

### D2.3 — Force-charge precedence preserved

**What:** D2.1 step 3 explicitly skips the proactive-on branch when `force_charge_active` is True (computed at `energy_pool.py:431-437`). This is a no-op for the user — force-charge already turns the EVSE on via its own path — but prevents `_proactive_offpeak_holds` from gaining membership during a force-charge window when the EVSE is on for a different reason.

**Acceptance Criteria — D2.3** — covered by `test_force_charge_active_skips_proactive_on` under D2.1.

---

### D2.4 — Toggle-semantics release note

**What:** Pre-deploy, add a paragraph to `docs/readmes/README_v<version>.md` (written at deploy time) calling out:

> The "EV TOU Management" toggle now also drives proactive off-peak charging. Previously it only paused EVSEs during peak/mid-peak. With this release, when the toggle is ON, URA will also ensure EVSEs are turned ON during off-peak unless a battery-protection guard (drain, fill-priority, grid-cap, arbitrage) is active. To opt out of the new off-peak behavior, turn the toggle OFF (which also disables peak-pause).

This is a Tier 2-DB review-B scope item (toggle semantics change). The release note is the user-facing record.

**Acceptance Criteria — D2.4** — README contains the paragraph; reviewer signs off in the live-validation pass.

---

## 6. D3 — Observability: `proactive_offpeak_holds` attribute on EV status sensor

**What:** Add a new attribute `proactive_offpeak_holds: list[str]` to the EV status sensor (`sensor.py:6571-6720` is the existing surface — `evse_force_charge_until_iso`). The attribute is read from `self._ev._proactive_offpeak_holds` on each sensor update.

**Why:** Without this, live validation has no way to confirm the new rule is firing on the right EVSEs without DB queries. The attribute is the authoritative live signal (URA's file logger sits at WARNING, INFO-level log lines won't help).

**Bug classes honored:**
- **#7 (stale data source)** — N/A, read directly from in-memory state.
- **#26 (high-frequency DB read)** — attribute read is pure-memory, no DB query.
- **#13/#21** — N/A, the attribute is a list of strings.

#### Acceptance Criteria — D3
- **Verify:** Sensor's `proactive_offpeak_holds` attribute reflects in-memory state within one sensor update cycle.
- **Sensor:** `sensor.ura_energy_coordinator_ev_status` attribute key `proactive_offpeak_holds` is a JSON list (empty during peak/mid_peak; populated during off-peak with EVSEs being held on by D2.1).
- **Test:** `test_ev_status_sensor_exposes_proactive_holds` in `quality/tests/test_ev_status_sensor.py` (extend existing file if present, else create).
- **Live:** During off-peak, `ha_states get sensor.ura_energy_coordinator_ev_status` returns attribute `proactive_offpeak_holds` listing at least one EVSE if a car is plugged in.

---

## 7. Tier 2-DB review framings (three parallel, framing-disjoint)

Per CLAUDE.md § Tier 2-DB and `feedback_db_sensitive_3x_targeted_reviews.md`. Run all three reviews in PARALLEL with the briefs below. No reviewer reads another reviewer's brief before submitting.

### Review A — Persistence correctness, restore correctness, staleness invariants

**Focus:** WS1 — D1.1 through D1.4. Existing rows in `evse_state` + `energy_state` are preserved by the new save calls (additive only, no DELETE). DAO read paths remain backward-compatible — old callers that pass no `max_age_hours` get the default 10h guard, which must not silently regress behavior on already-correct restart cycles. ISO string handling uses `dt_util.parse_datetime` everywhere (no `datetime.fromisoformat`). Save cadence honors the existing 15-min `_periodic_db_writes` rhythm; no new periodic timer is introduced (Bug Class #19/#42 vector). The new KV keys (`ev_force_charge_until`, `evse_fill_priority_paused`, `evse_proactive_offpeak_holds`) are field-by-field consistent with the existing pattern (`evse_grid_cap_paused`, `evse_battery_drain_paused`).

Specific checks:
1. Every save call has a matching restore call.
2. Every restore call handles `None` / parse failure gracefully (no exception escapes; `_LOGGER.warning` at most).
3. The staleness guard does NOT crash on a legacy row where `updated_at` is `None` or non-ISO (must skip gracefully, log INFO).
4. `_save_evse_state` per-tick cost (additional KV writes) is bounded — confirm 3-4 extra `INSERT OR REPLACE` calls per 15 min is below the SQLite write queue budget.
5. No DELETE introduced (Bug Class #25).
6. Switch RestoreEntity attribute path at `switch.py:802-854` remains coherent with the KV path — on conflict, KV wins. Verify the order of restore operations puts KV after Switch (or the resolution logic is explicit).

### Review B — Behavior change, precedence-chain integrity, toggle semantics, no-flap invariant

**Focus:** WS2 — D2.1 through D2.4 and the `_ev_tou_enabled` semantics widening. Verify the precedence-chain in `energy.py:2185-2272` is preserved: `determine_actions` (TOU) → arbitrage → excess_solar → grid_cap → drain → fill_priority. The pre-check at D2.1 step 2 prevents the visible on→off flap in the common case (guard set non-empty entering tick); confirm. Verify the manual-user-disable case re-enforces idempotently (the v4.7.x D1 philosophy at `energy_pool.py:457-460`). Trace end-to-end for each guard set: a guard fires NEWLY this tick → on-then-off in one tick → user-visible result is OFF (acceptable; matches excess-solar path today). Verify `_proactive_offpeak_holds` is cleared on every transition out of off-peak (D2.2). Verify the `_ev_tou_enabled` semantics change is loud enough in the release note (D2.4) that an operator won't be surprised by overnight charging.

Specific checks:
1. Decision-cycle ordering (`energy.py:2185, 2198, 2211, 2224, 2241, 2255`) unchanged.
2. No new signal dispatch (no new `async_dispatcher_send`); if any added, audit observation-mode gating (Bug Class #23).
3. The force-charge precedence (`energy_pool.py:_is_force_charge_active`) still wins over the new proactive-on branch.
4. `self_modulates` EVSEs (`energy_pool.py:309-320`) still receive proactive-on. Builder note must confirm this is intended or flag it.
5. Toggle semantics change: a user who has the TOU toggle OFF gets NO proactive-on (the gate at `energy.py:2184` still holds). A user who has it ON gets BOTH peak-pause AND off-peak-ensure-on. Confirm the release note matches.
6. Edge case: `tou_period == None` or unexpected string. Confirm graceful no-op (the `else` branch is currently a catch-all; the new code must not crash on a non-`peak`/`mid_peak` value).

### Review C — New surfaces, test-fixture authority, sensor attributes, test infrastructure

**Focus:** D3 + D1.3's new in-memory set + the new attribute on the EV status sensor + the new unit-test file `quality/tests/test_ev_offpeak_proactive.py`. Verify the test fixtures source their DB schema from `database.py` directly (NOT hand-copied DDL — per Tier 2-DB Review C protocol). The new `_proactive_offpeak_holds` set is initialized in `__init__`, pruned in `_prune_removed_evses`, persisted in `_save_evse_state`, restored in `_restore_evse_state` — all four sites must be present.

Specific checks:
1. `_proactive_offpeak_holds` initialized in `EVChargerController.__init__` (`energy_pool.py:~214`).
2. `_proactive_offpeak_holds` listed in `_prune_removed_evses` (`energy_pool.py:369-401`) `tracking_set` loop alongside the other six pause sets.
3. New sensor attribute is observation-mode-safe (sensor attributes can leak coordinator state even when observation mode is on; D3 attribute is informational only, no actions, so this is acceptable — but confirm).
4. Test file imports from production DAOs, does not redefine `CREATE TABLE` SQL.
5. Test file uses `dt_util` properly; no `sys.modules.setdefault("homeassistant.util.dt", ...)` to avoid the v4.7.x Bug Class #44 (cross-file `sys.modules` pollution).
6. AST regression test: `quality/tests/test_v4615_threadsafety.py::test_no_lambda_wrapping_async_create_task` still passes (no new lambda scheduler-callback patterns introduced; Bug Class #42).
7. AST regression test: `quality/tests/test_update_listener_async.py` still passes (no new sync update listeners; Bug Class #28).
8. Confirm `proactive_offpeak_holds` is a JSON-serializable list (not a `set` — HA serializes attributes to JSON for the WebSocket API; `set` would raise `TypeError`).

---

## 8. Bug-class honor roll (explicit)

| Class | How honored | Where to verify |
|---|---|---|
| #10 (cross-restart loss) | D1.1, D1.2, D1.3 add persistence; D1.4 bounds staleness | Reviewer A |
| #13 (DB returns strings) | All restores use `dt_util.parse_datetime`; `isinstance` guards on KV values | Reviewer A |
| #19 (untracked background tasks) | No new `hass.async_create_task` calls; save cadence reuses existing `_periodic_db_writes` | Reviewer A, C |
| #21 (tz-naive/tz-aware mix) | Save uses `dt_util.now().isoformat()`; restore uses `dt_util.parse_datetime` | Reviewer A |
| #23 (observation mode gating) | New branch inside existing `if not self._observation_mode:` (`energy.py:2174`); no new dispatch | Reviewer B, C |
| #25 (unbounded DELETE) | No DELETE in this cycle; staleness is a read-time filter | Reviewer A |
| #26 (high-frequency DB read) | New attribute is pure-memory; KV reads happen only on restart | Reviewer A, C |
| #28 (sync `add_update_listener`) | No new update listeners; AST regression test asserts | Reviewer C |
| #42 (lambda + async_create_task in scheduler) | No new scheduler callbacks; AST regression test asserts | Reviewer C |
| #43 (bookkeeping short-circuit defeated) | This is the class we are *fixing*. Enforcement loop re-issues `turn_on` idempotently. Manual user-disable is re-enforced next tick. `_proactive_offpeak_holds` is intent state, not "we already did this" short-circuit. | Reviewer B |
| #44 (sys.modules test contamination) | New test file uses isolated `dt_util` mocks; AST audit | Reviewer C |

---

## 9. Plan Completion Tracking

Items planned and explicitly NOT shipped in this cycle:

1. **Capacity / target-SoC / "charge by morning" promise — DEFERRED.** URA controls a switch and has no per-vehicle SoC readout. Honestly delivering a target-SoC by morning would require:
   - Per-EVSE configured battery capacity (kWh).
   - Per-EVSE configured nominal charge rate (kW), or learned from observed kWh-per-hour at the energy entity.
   - A scheduling model that projects "kWh needed by 06:00" against the remaining off-peak window.
   - A user-facing target-SoC input (Number entity) per EVSE.
   This is a separate feature cycle (Tier 2-DB, ~400-500 LoC). Track in BACKLOG.md under "EV scheduled-target charging." For now, the honest deliverable is "charging is enabled every off-peak hour unless a battery guard trips." This satisfies the operator's primary failure mode (car never charged by morning).

2. **`_paused_by_arbitrage` persistence — DEFERRED (intentional).** Arbitrage re-derives from `decision["arbitrage_phase"]` on the next tick (`energy.py:2194-2203`); the restart cost is at most one cycle of misattribution. Adding a fourth KV key for parity-of-shape is +5 LoC but adds save-cadence cost. If a future incident shows the misattribution causes a visible bug (e.g., NM trip during the wrong arbitrage phase), revisit. Track in TECH_DEBT.md.

3. **`self_modulates` opt-out for proactive-on — DEFERRED.** D2.1 turns on self-modulating EVSEs during off-peak (matches current `self_modulates` semantics: URA is the authority on the *pause* side; the EVSE is the authority on *modulation*). If the operator wants self-modulating EVSEs to NOT be auto-turned-on during off-peak (e.g., a smart-charger that has its own off-peak scheduler), add a per-EVSE config `auto_on_offpeak: bool` (default True). Plan-level note: do not ship this without operator request; YAGNI.

4. **Number entity for the staleness guard hours (D1.4) — DEFERRED.** Hardcoded 10h is fine for the operator's deployment. If a future incident shows the threshold is wrong, expose as a Number entity. Track in TECH_DEBT.md only if the cycle reveals friction.

5. **Cleanup method + nightly schedule for stale `evse_state` rows — DEFERRED.** Bug Class #27 (orphaned cleanup method) says every INSERT table needs a cleanup. `evse_state` uses `INSERT OR REPLACE` keyed on `evse_id`, so rows do not grow per restart — only stale-by-time for removed EVSEs. The `_prune_removed_evses` path already covers config-removal. Stale-by-time pruning is not urgent. Add a `cleanup_evse_state` DAO and wire to nightly maintenance in a future hygiene cycle.

---

## 10. Sequencing + ship plan

Single deploy. Inside the deploy, the implementation order is fixed:

1. **WS1 first** (D1.1, D1.2, D1.3, D1.4) — persistence machinery must exist before WS2 introduces intent-state that depends on it.
2. **WS2 second** (D2.1, D2.2, D2.3, D2.4 release note) — the behavior change.
3. **D3 last** (sensor attribute) — observability for live validation.

Tests written alongside each deliverable. Tier 2-DB three-reviewer pass before deploy.

Pre-deploy snapshot of affected `energy_state` row count by key and `evse_state` row count by `(paused_by_energy, excess_solar_active)` — for the post-deploy ±25% comparison required by Tier 2-DB protocol.

Live Validation (Review D) plan:
- After restart, confirm `ev_force_charge_until` key in `energy_state` exists or is absent based on prior force-charge usage.
- Confirm `evse_fill_priority_paused`, `evse_proactive_offpeak_holds` keys exist (may be empty JSON lists, that's fine).
- Confirm at least one EVSE attribute `proactive_offpeak_holds` is populated during off-peak with a plugged-in car.
- Confirm the EVSE switch is `on` during off-peak with no guards active.
- Confirm DB row `SELECT count(*) FROM energy_state WHERE key LIKE 'evse_%'` returns the expected number of rows (existing 2 keys + new 2-3 keys).

Per `feedback_record_live_validation_in_readme`: the post-restart Live Validation table replaces the prospective list in the README before cycle close.

---

## 11. Operator decisions (resolved 2026-06-07)

1. **Toggle reuse (Option A) vs new sub-toggle (Option B)?** — **RESOLVED: Reuse `_ev_tou_enabled` (Option A).** Its semantics widen from "pause EVSEs during peak/mid-peak" to "URA owns EVSE TOU behavior in both directions — pause during high-rate periods AND proactively ensure-on during off-peak." Operator directive: this widening MUST be documented in vibememo and at every site that reads/explains the toggle (switch helper text, release note, QUALITY_CONTEXT if it grows). Reviewer B verifies the widened semantics are surfaced loudly enough.
2. **Self-modulating EVSE behavior — proactive-on opt-in or implicit?** — **RESOLVED: Proactive (implicit-on).** Self-modulating EVSEs participate in off-peak ensure-on without a separate opt-in knob, consistent with the existing `self_modulates` scope. No new config surface.
3. **Staleness guard default — 10h, 12h, or 24h?** — **RESOLVED: 10h.** Operator chose the most conservative-against-stale-intent option. Re-derivation covers the guard-set pauses and `_force_charge_until` self-expires, so dropping anything older than 10h is safe; the only loss is a late-evening proactive hold if an outage straddles >10h into mid-morning, which the next decision cycle re-establishes anyway. `restore_evse_state` / `restore_energy_state_with_age` default `max_age_hours=10`.
4. **Should `_paused_by_arbitrage` persistence be in-scope after all?** — **RESOLVED: Persist for parity.** Add a new `energy_state` KV key `evse_arbitrage_paused` mirroring the grid-cap / battery-drain / fill-priority persistence pattern (+~5 LoC: save in `_save_evse_state`, restore in `_restore_evse_state`). Promotes WS1 to cover all five guard sets uniformly. Review A confirms save/restore symmetry for the added key.

All four decisions resolved 2026-06-07 — builder is unblocked.

---

## 12. References

- Source files end-to-end:
  - `custom_components/universal_room_automation/domain_coordinators/energy_pool.py:1-700`
  - `custom_components/universal_room_automation/domain_coordinators/energy.py:240-260, 760-930, 2170-2300, 2420-2440, 3530-3550, 3700-3730, 3755-3770`
  - `custom_components/universal_room_automation/domain_coordinators/energy_const.py:1-60`
  - `custom_components/universal_room_automation/database.py:860-945, 3640-3700, 3960-4000`
  - `custom_components/universal_room_automation/switch.py:770-900`
  - `custom_components/universal_room_automation/button.py:1380-1440`
  - `custom_components/universal_room_automation/sensor.py:6560-6720`
- Bug classes consulted: `docs/QUALITY_CONTEXT.md` §10, §13, §19, §21, §23, §25, §26, §28, §42, §43, §44.
- Prior cycles: v4.7.6 (EVSE solar-aware charging — Tier 2-DB precedent), v4.7.x D1/D3 (idempotent peak re-pause + force-charge button), v3.15.0 (`energy_state` KV introduction).
- Memory: `feedback_db_sensitive_3x_targeted_reviews.md`, `feedback_pre_deploy_zero_bugs_gate.md`, `feedback_fix_lows_in_cycle.md`, `feedback_parsimonious_room_config.md`, `project_v476_live.md`.
