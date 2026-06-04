# PLANNING v4.7.6 — EVSE Solar-Aware Charging

**Status:** Draft (planning)
**Author:** ura-planner
**Date:** 2026-05-29
**Tier:** **Tier 2-DB (three parallel reviewers, different framings)**
**Predecessor:** v4.7.5 (Zone Manager UX + canonical resolution)
**Production at plan time:** v4.7.4.4

---

## Tier Justification

This cycle does **not** match the formal Tier 2-DB trigger criteria in `CLAUDE.md`:

- No `database.py` DAO changes
- No DAO migration of ≥3 callers
- No payload shape change of a persisted record or dispatched event
- No new behavioral test infrastructure against real schemas

It is upgraded to Tier 2-DB **at the user's explicit request** (2026-05-29: *"Use tier 2 db quality since this code has been full of correctness issues"*). The framing-discipline rationale governs: the gate-logic in `energy_pool.py` has historically shipped correctness regressions (drain rule, `battery_ok or soc_recovered` OR clause, manual-override false positive at line 553) that **pairs of similarly-framed reviewers would converge on missing**. Three reviewers along orthogonal axes cannot share blind spots — the key reason the user invoked the upgrade. Reviews **run in parallel**, never sequentially.

Reviewer framings (locked in here, repeated at review-dispatch time):
1. **Reviewer A** — correctness + state-machine invariants
2. **Reviewer B** — async, lifecycle, restart resilience
3. **Reviewer C** — new surfaces + admin UX + cross-rule precedence

See `## Tier 2-DB Review Framings` below for the full per-reviewer scope.

---

## Context & Triggering Observation

During v4.7.5 live-validation aftermath:

- EV (Garage A) started charging at 7.4 kW with SOC=48%, battery began discharging at ~0.5 kW.
- URA's drain rule paused EV at 17:38 (correctly).
- 9 minutes later (17:47) URA **resumed** EV — even though SOC was still 51%, far below the 80% threshold.
- Root cause #1: the OR clause at `energy_pool.py:592` (`battery_ok or soc_recovered`) let "battery not draining this instant" override the SOC gate. Battery was charging at -9.5 kW one tick before resume because the EV was off — `battery_ok=True` for the wrong reason (transient equilibrium URA itself created).
- Root cause #2 (suspected): re-pause never fires next tick because the manual-override branch at `energy_pool.py:553-561` fires during `switch.turn_off` dispatch latency. HA state cache shows `is_on=True` while `_paused_by_battery_drain` still contains the entry → URA misreads its own pending dispatch as a user override → sets a 1-hour `EV_BATTERY_DRAIN_COOLDOWN` that suppresses both pause and resume.

This cycle hardens drain rule + introduces a new symmetric "fill-priority" pause + renames the misleading "Excess Solar Charging" switch to "EVSE Solar-Aware Charging" (one switch gates both turn-on and pause sides of solar-aware EV gating) + surfaces the state machine on the EV charging status sensor.

---

## In-Scope Files (read end-to-end during planning)

| File | Lines / focus | What this cycle changes |
|---|---|---|
| `custom_components/universal_room_automation/domain_coordinators/energy_pool.py` | 185-211 (state init), 213-270 (`_get_evse_state`), 272-353 (`determine_actions`), 375-467 (`determine_excess_solar_actions`), 469-522 (`determine_grid_cap_actions`), 524-613 (`determine_battery_drain_actions`), 615-706 (`determine_arbitrage_actions`), 751-794 (`get_status`); 803-928 (`SmartPlugController`) | Drain hardening, new `determine_fill_priority_actions` on both classes, idempotent re-pause, hybrid A+B `self_modulates`, two new state dicts, new tracking set, get_status expansion |
| `custom_components/universal_room_automation/domain_coordinators/energy.py` | 220-260 (config wiring), 2120-2220 (decision tick), 3700-3720 (drain SOC accessor) | Wire new fill-priority into decision tick, hold `_fill_priority_soc` runtime attr, expose accessor for new Number entity |
| `custom_components/universal_room_automation/domain_coordinators/energy_const.py` | 390-415 (existing EV CONF + DEFAULT block) | Add `CONF_ENERGY_FILL_PRIORITY_SOC` + `DEFAULT_FILL_PRIORITY_SOC = 80`, `CONF_ENERGY_FILL_PRIORITY_SAFETY_MARGIN_KWH`, per-EVSE `CONF_EVSE_SELF_MODULATES` key prefix |
| `custom_components/universal_room_automation/switch.py` | 667-670 (`ECExcessSolarSwitch` factory call) | Rename `excess_solar` → `evse_solar_aware`. **Preserve `unique_id` exactly.** Friendly name = "EVSE Solar-Aware Charging". |
| `custom_components/universal_room_automation/number.py` | (existing `excess_solar_soc` number) | Add `number.ura_energy_coordinator_fill_priority_soc` (default 80, min 50, max 95, step 5). |
| `custom_components/universal_room_automation/button.py` | EVSEForceChargeButton helper text | Update helper text to reference new `self_modulates` semantics. |
| `custom_components/universal_room_automation/sensor.py` | `EVChargingStatusSensor` `extra_state_attributes` | Add 7 new attrs (see D4). |
| `custom_components/universal_room_automation/translations/en.json` + `strings.json` | 848-850, 900-902 | New helper text for renamed switch, new Number entity, per-EVSE `self_modulates` checkbox |
| `custom_components/universal_room_automation/config_flow.py` | EV / EVSE section | Per-EVSE `self_modulates` checkbox (default `False`) |
| `quality/tests/test_energy_pool_drain.py` (new) | — | 9 named test stubs from D5 |

**Reads (no edits):**
- `docs/QUALITY_CONTEXT.md` — Bug Classes #7, #42, #45, #46, #47, #14 (config snapshot staleness), #20 (concurrent reload race)
- `graphify-out/GRAPH_REPORT.md` — cross-coordinator relationships

---

## Deliverables

### D1 — Drain rule hardening + idempotent re-pause + hybrid `self_modulates`

**Scope:** `energy_pool.py:524-613` (`EVPool.determine_battery_drain_actions`) and mirror on `energy_pool.py:859+` (`SmartPlugController.determine_battery_drain_actions`).

**Changes:**

1. **New per-EVSE config flag `evse_self_modulates: bool`** (default `False`, surfaced as a checkbox in config_flow for each configured EVSE).
   - When checked (Option A — explicit user opt-in): manual-override branch skipped entirely. URA is authority. Use for smart EVSEs with native solar / schedule modes (Emporia, Tesla Wall Connector).
   - When unchecked or unconfigured (Option B — default): smart manual-override detection runs.

2. **Two new per-EVSE state dicts on `EVPool.__init__`:**
   - `_pause_dispatch_ts: dict[str, float]` — `monotonic()` at the moment URA dispatches `switch.turn_off` for that EVSE. Cleared on resume.
   - `_observed_off_since_pause: dict[str, bool]` — `False` on dispatch; flips to `True` the first decision tick after dispatch when URA reads `state.is_on=False` from HA. Cleared on resume.

3. **Manual-override branch (Option B path) fires ONLY when ALL hold:**
   - `evse_id in self._paused_by_battery_drain`
   - `state.is_on=True`
   - `_observed_off_since_pause.get(evse_id, False) is True`  *(we saw it actually go off at some point)*
   - `monotonic() - _pause_dispatch_ts[evse_id] > 30.0`  *(grace window expired)*

   If `is_on=True` but `observed_off=False` → never saw it go off → either dispatch hasn't propagated OR EVSE auto-re-enabled inside the HA state-cache window → treat as re-pause-needed, NOT manual override.
   If grace not expired → recent dispatch, treat as stale state read → re-pause if conditions still warrant it.

4. **Drop the `if evse_id not in self._paused_by_battery_drain:` short-circuit on the pause action** (line 572). Mirror the v4.7.x TOU pattern at `energy_pool.py:319-323`. URA re-pauses every tick the conditions are met. Set `_pause_dispatch_ts[evse_id] = monotonic()` and `_observed_off_since_pause[evse_id] = False` on every actual dispatch.

5. **State-update on every tick (regardless of action):**
   - When `evse_id in self._paused_by_battery_drain` AND `state["is_on"] is False` AND `_observed_off_since_pause.get(evse_id) is False` → set `_observed_off_since_pause[evse_id] = True`. (We finally observed it off.)

6. **Refined resume condition.** Replace `battery_ok or soc_recovered` at line 592 with:
   ```python
   battery_out_of_capacity = (
       battery_ok
       and battery_soc is not None
       and reserve_soc is not None
       and battery_soc <= reserve_soc + 2  # at reserve floor — capacity exhausted
   )
   soc_recovered = (
       battery_soc is not None
       and battery_soc >= soc_threshold + 5  # solar recharge clear of threshold
   )
   if battery_out_of_capacity or soc_recovered:
       # resume
   ```
   `reserve_soc` sourced from `self._battery.reserve_soc` via a new optional kwarg `reserve_soc: int | None` on `determine_battery_drain_actions`. If `None` (test paths, missing Enpower), `battery_out_of_capacity` defaults to `False` and only `soc_recovered` permits resume — safer than today's behavior.

7. **Mirror all of (1)–(6) on `SmartPlugController.determine_battery_drain_actions`.** L1 chargers have the same observable surface (`switch.turn_off` dispatch latency, possible auto-resume on dumb hardware, no native solar mode but the same hybrid model still applies because the user may manually toggle the plug). `evse_self_modulates` becomes `plug_self_modulates` per plug — same default `False`.

8. **Cleanup on resume / cooldown engage:**
   - `_pause_dispatch_ts.pop(evse_id, None)`
   - `_observed_off_since_pause.pop(evse_id, None)`

9. **EVSE add/remove lifecycle:** when an EVSE entry is removed from `self._evse` (config flow remove), purge all four per-EVSE dicts (`_paused_by_battery_drain`, `_battery_drain_cooldown`, `_pause_dispatch_ts`, `_observed_off_since_pause`). Add a `_prune_removed_evses()` helper called from `EVPool.__init__` and from a new `update_evse_config()` method (called when config flow rewrites entries). Without this, stale entries leak across config edits.

#### D1 — Acceptance Criteria
- **Verify:** After URA dispatches `switch.turn_off` for `garage_a` while drain conditions hold, re-asserting `switch.garage_a = on` within 5s does NOT engage the 1-hour cooldown.
- **Verify:** After grace expires (30s+) and URA observes `state.is_on=False` once, a subsequent `state.is_on=True` (with `self_modulates=False`) engages cooldown.
- **Verify:** With `self_modulates=True`, URA re-pauses on every decision tick that conditions hold, regardless of external state changes. No cooldown ever engages on this EVSE.
- **Verify:** Drain rule does NOT resume EV mid-day at SOC=51 when battery is briefly at equilibrium because EV is paused. (Refined `battery_out_of_capacity` requires `battery_soc <= reserve_soc + 2`.)
- **Verify:** Drain rule DOES resume EV at end-of-solar-day when SOC has fallen to `reserve_soc + 2` and battery has stopped discharging.
- **Sensor:** `sensor.ura_energy_coordinator_ev_charging_status` attribute `evse_config.garage_a.self_modulates` reflects the configured value.
- **Sensor:** `pause_dispatch_state.garage_a.observed_off` flips `false → true` exactly once per pause cycle.
- **Test:** `test_drain_smart_self_modulates_idempotent_repause` (D5 test #1)
- **Test:** `test_drain_smart_default_config_repause` (D5 test #2)
- **Test:** `test_drain_real_dumb_user_override` (D5 test #3)
- **Test:** `test_drain_dispatch_latency_no_false_cooldown` (D5 test #4)
- **Test:** `test_drain_instant_smart_auto_resume` (D5 test #5)
- **Test:** `test_drain_smart_evse_misconfigured` (D5 test #6)
- **Test:** `test_drain_end_of_solar_day_resume` (D5 test #7)
- **Test:** `test_drain_transient_equilibrium_no_resume` (D5 test #8)
- **Live:** Tail HA logs post-deploy for 1 decision cycle: confirm at least one `_observed_off_since_pause` flip in the new sensor attribute when a real drain pause happens.

---

### D2 — New `determine_fill_priority_actions` (primary rule)

**Scope:** `energy_pool.py` — new method on `EVPool` and on `SmartPlugController`. Wired into `energy.py:_async_evaluate_dynamic_presets` decision tick around line 2183 (next to drain check), gated by `self._excess_solar_enabled` (same switch as excess solar — see D3).

**Method signature (EVPool):**
```python
def determine_fill_priority_actions(
    self,
    soc: float | None,
    remaining_forecast_kwh: float | None,
    tou_period: str,
    soc_threshold: int,
    excess_solar_kwh_threshold: float,
    safety_margin_kwh: float = 1.0,
) -> list[dict[str, Any]]:
```

**PAUSE conditions** (all must hold):
- `tou_period != "peak"` (peak handled by TOU pause — never override peak with fill-priority pause)
- `soc is not None and soc < soc_threshold`
- `remaining_forecast_kwh is not None and remaining_forecast_kwh >= excess_solar_kwh_threshold`
- EVSE currently `is_on` (otherwise nothing to do)

**RESUME conditions** (either):
- `soc is not None and soc >= soc_threshold` (battery filled to target)
- `remaining_forecast_kwh < (excess_solar_kwh_threshold - safety_margin_kwh)` (forecast no longer healthy enough to withhold EV)

**Tracking:** new instance attr `self._paused_by_fill_priority: set[str]`.

**Idempotent re-pause:** identical to D1 — drop any `if evse_id not in self._paused_by_fill_priority:` guard on the pause action. Re-pause every tick conditions hold.

**Hybrid `self_modulates`:** identical semantics to D1. Share the same `_pause_dispatch_ts` and `_observed_off_since_pause` dicts — they're per-EVSE, not per-rule. (Justification: only one URA-initiated dispatch can be pending at a time; if drain dispatched it, fill-priority sees observed_off=True; if fill-priority then dispatches it again that tick, it re-stamps. Same dict is correct because both rules have the same dispatch surface.)

**Cross-rule precedence** (decision tick order; existing tick order preserved + fill-priority inserted right after drain):
1. TOU pause (peak / mid_peak) — `determine_actions`
2. Arbitrage compound-load — `determine_arbitrage_actions`
3. Excess solar turn-ON — `determine_excess_solar_actions`
4. Grid import cap — `determine_grid_cap_actions`
5. Battery drain — `determine_battery_drain_actions`
6. **Fill-priority pause (NEW)** — `determine_fill_priority_actions`
7. Smart plug TOU + drain + fill-priority

Resume gating in fill-priority: do not resume if EVSE is in any other pause set (`_paused_by_us`, `_paused_by_grid_cap`, `_paused_by_battery_drain`, `_paused_by_arbitrage`). Discard from `_paused_by_fill_priority` silently when another reason holds — mirrors the existing pattern at lines 595-600.

**Excess-solar-active interaction:** when fill-priority would pause but the EVSE is in `_excess_solar_active` → fill-priority deferred to next tick AND log a debug breadcrumb. Excess solar wins this tick. Justification: if excess solar (SOC≥95%) is firing, SOC≥95 ≥ any sensible fill_priority_soc, so the pause-condition `soc < soc_threshold` is already False. This is belt-and-suspenders.

**SmartPlugController mirror:** same shape, same tracking, no `_excess_solar_active` interaction (plugs don't participate in excess solar turn-ON today).

#### D2 — Acceptance Criteria
- **Verify:** With SOC=51, EV pulling 7 kW, solar 18 kW, battery charging slowly, `fill_priority_soc=80`, off-peak TOU → fill-priority pauses EV within one decision tick (≤5 min).
- **Verify:** L1 plug pauses under same conditions (`SmartPlugController` parity).
- **Verify:** With SOC=80, fill-priority resumes EV that it paused (and only EVSEs it paused — `_paused_by_fill_priority` membership check).
- **Verify:** With `remaining_forecast_kwh=2.0` and `excess_solar_kwh_threshold=5.0`, `safety_margin=1.0` → forecast condition fails (`2.0 < 4.0`), fill-priority resumes.
- **Verify:** During peak TOU, fill-priority is bypassed; TOU pause wins.
- **Verify:** Idempotent re-pause holds for fill-priority same as for drain (re-assert switch on, URA re-pauses next tick).
- **Sensor:** `sensor.ura_energy_coordinator_ev_charging_status` attribute `paused_by_fill_priority` is `["garage_a"]` when active, `[]` when not.
- **Sensor:** Attribute `fill_priority_solar_ok` is `true` when forecast >= threshold, `false` otherwise.
- **Test:** `test_fill_priority_pause_off_peak_low_soc_healthy_solar` (D5 test #9 family)
- **Test:** `test_fill_priority_resume_at_target_soc` (D5)
- **Test:** `test_fill_priority_resume_on_forecast_decay` (D5)
- **Test:** `test_fill_priority_bypassed_during_peak` (D5)
- **Test:** `test_fill_priority_smart_plug_parity` (D5)
- **Test:** `test_fill_priority_idempotent_repause` (D5)
- **Test:** `test_fill_priority_defers_to_excess_solar` (D5)
- **Live:** Within 1 hour of next clear-sky day with EV plugged in below 80%, observe `paused_by_fill_priority` populated and a corresponding `EV: fill-priority pausing garage_a` log line.

---

### D3 — UX renames, new Number entity, helper text

#### D3.1 — Rename Excess Solar switch → EVSE Solar-Aware Charging

**File:** `switch.py:667-670`

Change `ECExcessSolarSwitch` factory call:
```python
# BEFORE
ECExcessSolarSwitch = _ec_switch_factory(
    "_excess_solar_enabled", "excess_solar",
    "Excess Solar Charging", "mdi:solar-power", default=False,
)
# AFTER
ECEVSESolarAwareSwitch = _ec_switch_factory(
    "_excess_solar_enabled", "evse_solar_aware",
    "EVSE Solar-Aware Charging", "mdi:solar-power", default=False,
)
```

**unique_id stability:** `_ec_switch_factory` derives unique_id from the slug argument. Changing the slug `"excess_solar"` → `"evse_solar_aware"` would break unique_id continuity and orphan HACS history. **Pin the unique_id to the legacy slug** explicitly: add a `unique_id_override` kwarg to the factory and pass `unique_id_override="excess_solar"` so the new switch keeps the old unique_id while exposing the new entity_id / friendly name.

**Backward-compat entity_id alias for one release:** during platform setup, register an `EntityRegistry` migration step that renames the old entity_id (`switch.ura_energy_coordinator_excess_solar_charging`) to the new one (`switch.ura_energy_coordinator_evse_solar_aware_charging`) via the registry's entity_id remapping API — preserves user-facing dashboards. Bug Class #46 awareness: this migration must run AT MOST ONCE per entry setup and must not call `async_update_entry`. Use `async_get(hass).async_update_entity(entity_id, new_entity_id=...)` instead.

**Helper text (translations/en.json + strings.json key `energy_excess_solar_enabled`):**
> "Manages EV charging based on solar production and battery state. When battery is full (≥ Excess Solar SOC) and solar surplus is available, EVSEs turn ON even during off-peak pause. When battery is below the Fill-Priority SOC and solar forecast is healthy, EVSEs PAUSE so the battery fills first. Off-peak TOU pause and battery drain protection run independently."

#### D3.2 — New `number.ura_energy_coordinator_fill_priority_soc`

- Min 50, max 95, step 5, default 80, unit `%`.
- Persisted via RestoreEntity (existing Number pattern in URA).
- Backed by new runtime attr `EnergyCoordinator._fill_priority_soc` and accessor pair (`fill_priority_soc` property + `set_fill_priority_soc(value)`), mirroring the existing `ev_battery_drain_soc` pair at `energy.py:3704-3716`.
- Seeded from `entry.options.get(CONF_ENERGY_FILL_PRIORITY_SOC, DEFAULT_FILL_PRIORITY_SOC)` at `EnergyCoordinator.__init__` (next to the existing `_excess_solar_soc` wiring at line 231-233).
- Helper text (translations key `energy_fill_priority_soc`):
  > "When SOC is below this and solar forecast is healthy, URA pauses EV charging so the battery fills first. Default 80%. Existing Excess Solar SOC (default 95%) remains the turn-ON threshold — the middle band (80–95) lets EVs run on their TOU schedule without solar-aware interference."

#### D3.3 — Existing `number.ura_energy_coordinator_excess_solar_soc` stays

- Unchanged: default 95, min/max/step unchanged.
- Helper text refreshed to clarify it is now the **turn-ON** threshold only:
  > "When SOC is at or above this and solar forecast is healthy, URA turns EVSEs ON even during off-peak pause. Default 95%."

#### D3.4 — Per-EVSE `self_modulates` checkbox in config flow

In the EV / EVSE configuration step of the energy config flow, add a checkbox per configured EVSE (e.g., `garage_a_self_modulates`, `garage_b_self_modulates`). Default `False`. Helper text:
> "URA re-pauses an EVSE that turns itself back on. Check this for smart EVSEs with native solar or schedule modes (Emporia, Tesla Wall Connector) — URA will re-pause every cycle. Leave unchecked for any other hardware — URA will detect a real user override (toggling the switch in HA) and back off for 1 hour, while still re-pausing across dispatch lag or instant auto-resumes."

Stored as part of the per-EVSE config dict at `EVPool._evse[evse_id]["self_modulates"]`.

Mirror for plugs: per-plug checkbox `plug_self_modulates` in the smart-plug step. Default `False`.

#### D3.5 — EVSE Force-Charge button helper-text update

`button.py` — update the EVSEForceChargeButton helper text:
> "Override URA's solar-aware EV gating for the next 30 minutes. Use this when an EVSE is marked self-modulating (URA re-pauses every cycle) but you need it to charge now regardless of solar or battery state. Resets automatically after the window expires; press again to extend."

#### D3 — Acceptance Criteria
- **Verify:** Switch unique_id is unchanged across the rename (query entity registry pre/post). HACS history is preserved.
- **Verify:** Legacy entity_id `switch.ura_energy_coordinator_excess_solar_charging` redirects to `switch.ura_energy_coordinator_evse_solar_aware_charging` for at least v4.7.6.
- **Verify:** Setting `number.ura_energy_coordinator_fill_priority_soc` from UI persists across HA restart (RestoreEntity round-trip).
- **Verify:** Setting `number.ura_energy_coordinator_fill_priority_soc` to 75 changes the runtime `EnergyCoordinator._fill_priority_soc` to 75 without restart.
- **Verify:** Toggling `garage_a_self_modulates=True` in config flow flips `EVPool._evse["garage_a"]["self_modulates"]` after entry reload.
- **Sensor:** `sensor.ura_energy_coordinator_ev_charging_status` attribute `evse_config.garage_a.self_modulates` reflects current config; `.source` is `"explicit"` if set in flow, `"default"` if missing.
- **Test:** `test_excess_solar_switch_unique_id_preserved`
- **Test:** `test_legacy_entity_id_redirects`
- **Test:** `test_fill_priority_soc_number_restore`
- **Test:** `test_self_modulates_per_evse_round_trip`
- **Live:** Open HA UI, confirm friendly name = "EVSE Solar-Aware Charging", helper text matches D3.1 spec, new Number entity visible.

---

### D4 — Visibility: 7 attrs on `sensor.ura_energy_coordinator_ev_charging_status`

Append to `EVPool.get_status()` (and propagated through the sensor's `extra_state_attributes`). All values derive from real state — no fabrication.

1. **`paused_by_fill_priority: list[str]`** — pure echo of `list(self._paused_by_fill_priority)`.
2. **`pause_reason_human: dict[str, str]`** — one-line plain-English per EVSE, computed from the active pause set:
   ```
   garage_a: "holding for battery fill (SOC 51 < 80, solar healthy)"
   garage_b: "TOU peak pause until 21:00"
   ```
   Priority order matches decision tick: fill_priority > drain > grid_cap > arbitrage > TOU > excess_solar > "idle"/"charging"/"off". `None`-safe if SOC unknown ("SOC unknown").
3. **`cooldowns: dict[str, dict[str, str]]`** — surface `_battery_drain_cooldown`:
   ```
   garage_a: {"expires": "18:23 CDT", "reason": "manual_override_detected"}
   ```
   `expires` formatted via `dt_util.now()`-aware local-time conversion (Bug Class #11). `reason` is hardcoded `"manual_override_detected"` for now (only cooldown source today); if D1's smart-detection ever engages cooldown, this is still accurate.
4. **`fill_priority_target_soc: int`** — echo of `self._fill_priority_soc` (threaded in via a new optional kwarg on `get_status()`).
5. **`fill_priority_solar_ok: bool`** — `(remaining_forecast_kwh or 0) >= excess_solar_kwh_threshold`. Computed at the decision tick site and passed into `get_status()` via a new optional kwarg, OR cached on `EVPool` after each `determine_fill_priority_actions` call. Plan: cache on `EVPool` to keep `get_status()` pure.
6. **`evse_config: dict[str, dict[str, Any]]`** —
   ```
   garage_a: {"self_modulates": false, "source": "default"}
   garage_b: {"self_modulates": true, "source": "explicit"}
   ```
   `source` is `"explicit"` if the key was present in `self._evse[evse_id]`, `"default"` otherwise. Lets a user see WHY URA is or isn't honoring a manual switch flip.
7. **`pause_dispatch_state: dict[str, dict[str, Any]]`** —
   ```
   garage_a: {
       "last_dispatch": "17:38:14",  # local time, ISO-formatted
       "observed_off": true,
       "grace_expires": "17:38:44"  # last_dispatch + 30s, local
   }
   ```
   Only present for EVSEs with a non-None `_pause_dispatch_ts` entry. Lets the user / dev see exactly why the manual-override decision did or didn't fire on the last tick.

**L1 plug parity (added 2026-05-29 per user):** ALL 7 attrs above MUST include L1 plug entries as peer keys alongside EVSEs. Per D6.3, L1 plugs surface in `ev_charging_status` with the same shape. So:
- `paused_by_fill_priority: ["garage_a", "moes_plug_garage_a", ...]` — flat list, mixed.
- `pause_reason_human: {garage_a: "...", moes_plug_garage_a: "..."}` — same dict, L1 entries treated identically.
- `cooldowns: {moes_plug_garage_a: {...}}` — applies when D1 cooldown engages on plug (`SmartPlugController._battery_drain_cooldown`).
- `evse_config: {moes_plug_garage_a: {self_modulates: false, source: "default"}}` — L1 plug shows same shape; `self_modulates` per D3.4 per-plug checkbox.
- `pause_dispatch_state: {moes_plug_garage_a: {...}}` — applies once D1's `_pause_dispatch_ts` and `_observed_off_since_pause` are mirrored on `SmartPlugController` (already in D1 scope).

Single keyspace for all EVSE-class devices simplifies dashboards and matches the user's "L1 = small EVSE" framing.

**NM trip on first fill-priority pause per day** — informational LOW NM alert dispatched from `energy.py` on the transition `_paused_by_fill_priority: empty → non-empty` (track previous-tick state for edge detection). Message: `"EVSE paused for battery fill (SOC {soc}%, target {target}%, solar forecast {remaining:.1f} kWh remaining)"`. Severity: LOW. Respects observation mode (Bug Class #23 — gate at dispatch, not in handler).

#### D4 — Acceptance Criteria
- **Verify:** All 7 attrs render on `sensor.ura_energy_coordinator_ev_charging_status` after restart, with sensible values (lists/dicts/bools/ints — not `None`, not strings of `None`).
- **Verify:** `pause_reason_human.garage_a` reads cleanly in dashboard markdown without HTML escaping issues.
- **Verify:** `cooldowns.garage_a.expires` is local timezone, not UTC (Bug Class #11).
- **Verify:** `pause_dispatch_state.garage_a.last_dispatch` is present only after URA has dispatched a pause for `garage_a`; absent on cold start.
- **Verify:** NM trip fires exactly once per day on first fill-priority pause; does NOT fire again on idempotent re-pause of the same tick or on subsequent same-day pauses.
- **Sensor:** `sensor.ura_energy_coordinator_ev_charging_status` exposes the 7 attrs verbatim per names above.
- **Test:** `test_get_status_attrs_shape_and_types`
- **Test:** `test_pause_reason_human_precedence`
- **Test:** `test_cooldowns_local_timezone`
- **Test:** `test_pause_dispatch_state_absent_on_cold_start`
- **Test:** `test_nm_trip_once_per_day_fill_priority`
- **Live:** Inspect sensor attributes after a real pause: all 7 keys present, types match spec.

---

### D5 — Test coverage (named test stubs)

New test file: `quality/tests/test_energy_pool_drain.py` + `quality/tests/test_energy_pool_fill_priority.py`. The 9 stubs from the backlog memory are mapped to concrete test names below. Each test drives `EVPool` (or `SmartPlugController`) directly with mocked HA state, asserts on returned action list AND on internal state-set membership AND on `get_status()` output.

| # | Stub from backlog | Concrete test name | File |
|---|---|---|---|
| 1 | "Adversarial smart EVSE, explicit opt-in" | `test_drain_smart_self_modulates_idempotent_repause` | `test_energy_pool_drain.py` |
| 2 | "Adversarial smart EVSE, default config" | `test_drain_smart_default_config_repause` | `test_energy_pool_drain.py` |
| 3 | "Real dumb-EVSE user override" | `test_drain_real_dumb_user_override` | `test_energy_pool_drain.py` |
| 4 | "Dispatch latency" | `test_drain_dispatch_latency_no_false_cooldown` | `test_energy_pool_drain.py` |
| 5 | "Instant smart auto-resume" | `test_drain_instant_smart_auto_resume` | `test_energy_pool_drain.py` |
| 6 | "Smart EVSE misconfigured" (self_modulates=True on dumb hw) | `test_drain_smart_evse_misconfigured` | `test_energy_pool_drain.py` |
| 7 | "End-of-solar-day" | `test_drain_end_of_solar_day_resume` | `test_energy_pool_drain.py` |
| 8 | "Transient equilibrium" | `test_drain_transient_equilibrium_no_resume` | `test_energy_pool_drain.py` |
| 9 | "Restart resilience" (reset on init per memory decision) | `test_drain_dispatch_state_resets_on_init` | `test_energy_pool_drain.py` |

Plus the fill-priority family in `test_energy_pool_fill_priority.py`:
- `test_fill_priority_pause_off_peak_low_soc_healthy_solar`
- `test_fill_priority_resume_at_target_soc`
- `test_fill_priority_resume_on_forecast_decay`
- `test_fill_priority_bypassed_during_peak`
- `test_fill_priority_smart_plug_parity`
- `test_fill_priority_idempotent_repause`
- `test_fill_priority_defers_to_excess_solar`

Plus UX + visibility tests in `test_evse_solar_aware_ux.py`:
- `test_excess_solar_switch_unique_id_preserved`
- `test_legacy_entity_id_redirects`
- `test_fill_priority_soc_number_restore`
- `test_self_modulates_per_evse_round_trip`
- `test_get_status_attrs_shape_and_types`
- `test_pause_reason_human_precedence`
- `test_cooldowns_local_timezone`
- `test_pause_dispatch_state_absent_on_cold_start`
- `test_nm_trip_once_per_day_fill_priority`

Plus a **config-flow runtime smoke test** (pre-deploy gate per user-coined zero-bugs gate, 2026-05-29):
- `test_config_flow_evse_step_imports_and_renders` — instantiate the energy config flow, drive through the EVSE step, assert it returns a valid `SchemaCommonFlowFormStep` without `ImportError`. Catches the v4.7.4.2 class of failure that source-grep AST tests miss.

**Pre-deploy zero-bugs gate (mandatory per user 2026-05-29):** before `deploy.sh`:
```bash
# Conflict markers
grep -rn '^<<<<<<<\|^=======\|^>>>>>>>' custom_components/universal_room_automation/ && exit 1
# Bytecode compile changed files
python3 -m py_compile custom_components/universal_room_automation/domain_coordinators/energy_pool.py \
  custom_components/universal_room_automation/domain_coordinators/energy.py \
  custom_components/universal_room_automation/domain_coordinators/energy_const.py \
  custom_components/universal_room_automation/switch.py \
  custom_components/universal_room_automation/number.py \
  custom_components/universal_room_automation/button.py \
  custom_components/universal_room_automation/sensor.py
# Cycle tests
PYTHONPATH=quality python3 -m pytest quality/tests/test_energy_pool_drain.py \
  quality/tests/test_energy_pool_fill_priority.py \
  quality/tests/test_evse_solar_aware_ux.py -v
# Full suite baseline diff
PYTHONPATH=quality python3 -m pytest quality/tests/ -v --tb=line
```

---

### D6 — EVSE TOU toggle unification + L1 plug visibility parity

**User decision 2026-05-29 mid-planning:** L1 plugs should be treated like a "smaller lower-voltage EVSE as much as possible." Today the EV TOU Management toggle gates only `EVPool.determine_actions(period)` at `energy.py:2131`, leaving `SmartPlugController.determine_actions(period)` at `energy.py:2203` always-armed — an asymmetric scope that contradicts the rest of this cycle's L1 parallelism.

#### D6.1 — Gate `SmartPlugController.determine_actions` under `_ev_tou_enabled`

`energy.py:2203` — wrap the existing call:
```python
# v4.7.6 D6.1: L1 plugs follow the same EVSE TOU gate as L2 EVSEs.
if self._ev_tou_enabled:
    plug_actions = self._smart_plugs.determine_actions(period)
    for action_spec in plug_actions:
        await self._execute_service_action(action_spec)
```
No new state, no new toggle. Reuses the existing `_ev_tou_enabled` boolean. ~5 LoC.

#### D6.2 — Rename the toggle's friendly name (NOT entity_id)

Friendly name: `"EVSE TOU Management"` (was `"EV TOU Management"`). Entity_id stays `switch.ura_energy_coordinator_ev_tou_management` for HACS / dashboard / automation continuity. Helper text:
> "Pauses ALL EVSE-class devices (L2 wall connectors and L1 plug-style chargers) during peak and mid-peak TOU periods. Each device's `self_modulates` flag (in its config step) governs whether URA enforces idempotent re-pause or honors external HA automation."

Strings.json + translations/en.json update; no `unique_id` change. Reuses the same rename-without-breaking-history pattern from D3.1.

#### D6.3 — L1 plugs surface as peer entries in `ev_charging_status`

Extend `EVPool.get_status()` (or coordinate with `SmartPlugController.get_status()`) to include each configured L1 plug as a top-level dict entry with the same shape as `garage_a` / `garage_b`:
```python
moes_plug_garage_a: {
    "is_on": true,
    "power": 1440,            # estimated from EVSE_ESTIMATED_POWER_W (L1 fallback)
    "status": "on",           # plain switch state; L1 plugs have no native "Charging" attr
    "charging": true,         # boolean: is_on AND power > threshold OR is_on AND not paused
    "power_source": "switch_status",  # always for L1 (no power sensor on dumb plugs)
    "energy_status": "charging" | "paused_by_battery_drain" | "paused_by_fill_priority" | "paused_by_tou" | "off"
}
```

For L1 plugs without a power sensor, `power` falls back to `EVSE_ESTIMATED_POWER_W` (or a new `L1_ESTIMATED_POWER_W = 1440` ~12A @ 120V if the existing 7600 W estimate is L2-specific — pick at build time after checking const). `charging` is True when `is_on` AND not in any `paused_by_*` set.

Implementation note: `EVPool` doesn't own plug state; either (a) `EVPool.get_status()` accepts an injected `plug_status: dict` from `SmartPlugController.get_status()` at the sensor's `extra_state_attributes` site, or (b) a shared helper merges the two. Reviewer C is responsible for flagging the cleanest pattern.

#### D6.4 — D3.4 per-plug `self_modulates` checkbox already covered

Already in D3.4 scope. No change here, just call out: per-plug checkbox has identical semantics to per-EVSE checkbox. Helper text on the plug step mirrors D3.4's EVSE text with "L1 plug" substituted for "EVSE."

#### D6 — Acceptance Criteria
- **Verify:** `switch.ura_energy_coordinator_ev_tou_management` set to OFF → next decision tick, `SmartPlugController.determine_actions(period)` is NOT invoked even during peak/mid_peak (no L1 plug TOU pause).
- **Verify:** Friendly name of the switch reads "EVSE TOU Management" in HA UI; entity_id and unique_id unchanged.
- **Verify:** `sensor.ura_energy_coordinator_ev_charging_status` lists each configured L1 plug as a top-level dict entry with the 6-key shape (is_on / power / status / charging / power_source / energy_status).
- **Verify:** All 7 D4 attrs include L1 plug entries alongside EVSE entries.
- **Sensor:** `ev_charging_status.moes_plug_garage_a.charging` reflects `(is_on AND not in any paused_by_* set)`.
- **Test:** `test_d6_ev_tou_toggle_gates_smart_plug_actions` — toggle OFF, assert SmartPlugController.determine_actions NOT called for next tick.
- **Test:** `test_d6_switch_friendly_name_updated_unique_id_preserved`.
- **Test:** `test_d6_l1_plug_appears_in_ev_charging_status` — assert peer-entry shape.
- **Test:** `test_d6_l1_plug_self_modulates_round_trip` — per-plug checkbox config-flow round-trip (covers D3.4 in plug context).
- **Live:** Toggle EVSE TOU Management OFF during peak; confirm L1 plug stays on. Toggle back ON; confirm L1 plug pauses on next tick.

**LoC impact:** +35-55 production, +60-80 tests. Net cycle total: ~296-316 LoC production + ~520-540 LoC tests. Still within Tier 2-DB review band.

---

## Bug Class Edge Cases (cross-cycle checklist)

| Class | Risk surface in this cycle | Mitigation |
|---|---|---|
| **#7 Stale data source** | Cooldown / dispatch_ts comparing against `_time.monotonic()` — monotonic survives across DB queries but resets on restart. | Reset-on-init explicitly documented (D1 #9 lifecycle). No DB persistence for these. |
| **#11 UTC vs local timezone** | `cooldowns.{evse}.expires` and `pause_dispatch_state.{evse}.last_dispatch` formatted for human display. | Use `dt_util.now()` and `.astimezone(now.tzinfo)` before `.strftime`. Test `test_cooldowns_local_timezone`. |
| **#14 Config snapshot staleness** | `_fill_priority_soc` and `_excess_solar_soc` are read at `__init__` time. User changes via Number entity must take effect immediately. | Existing `set_ev_battery_drain_soc` pattern (energy.py:3709) is the model. Pair `fill_priority_soc` property + setter, refreshed at decision tick via accessor not at init. |
| **#20 Concurrent reload race** | Per-EVSE checkbox added to energy config flow — no cross-entry update. Switch rename does NOT call `async_update_entry` on another entry. | Avoid any cross-entry mutation. Entity registry rename is local to URA's entry. |
| **#22 Enum value mismatch** | New NM alert with `hazard_type="evse_fill_priority"` (informational). Verify any signal handler downstream uses `.value` strings if relevant. | Hazard type is informational LOW; no safety-critical handler subscribes today. Document in code comment. |
| **#23 Observation mode gating** | New NM trip in D4. | Gate at dispatch site in `energy.py` next to existing `_send_nm_alert` calls (lines 2192-2200). Inherits observation-mode wrapper. |
| **#42 Lambda + `async_create_task`** | No new scheduler callbacks in this cycle. | Verify D4's NM trip uses existing `await self._send_nm_alert(...)` (already async, no lambda wrap). |
| **#45 Lambda closure stale** | None — no new lambdas at module/init scope. | N/A. Document explicitly during review. |
| **#46 `async_update_entry` re-entrancy** | Entity registry rename (D3.1) and per-EVSE config flow step. | Use `entity_registry.async_update_entity()` (not `async_update_entry`). Per-EVSE checkbox writes via standard options-flow path; no nested `async_update_entry`. |
| **#47 Lazy canonical resolution** | N/A — this cycle doesn't touch canonical resolution / zone manager. | N/A. |

---

## Tier 2-DB Review Framings (parallel, locked-in)

### Reviewer A — Correctness + state-machine invariants

**Mandate:** prove pause/resume invariants hold across the A/B hybrid for every reachable state combination.

**Required deliverable:** state-machine table covering all combinations of:
- `self_modulates ∈ {True, False}`
- `evse_id ∈ _paused_by_battery_drain ∈ {True, False}`
- `state.is_on ∈ {True, False}`
- `_observed_off_since_pause.get(evse_id) ∈ {True, False, missing}`
- `monotonic() - _pause_dispatch_ts[evse_id] > 30 ∈ {True, False, missing}`
- `cooldown_expiry > now ∈ {True, False, None}`

Expected action per cell: `pause_dispatched`, `cooldown_engaged`, `idempotent_repause`, `noop`, `resume`, `discard_from_set`.

**Cross-checks:**
- Misconfiguration: `self_modulates=True` on dumb hardware (user toggles switch on; URA must NOT engage cooldown — must idempotently re-pause; user must use Force-Charge to actually override).
- Misconfiguration: `self_modulates=False` on smart hardware that auto-resumes inside HA state-cache window (D5 test #5 path).
- Refined `battery_out_of_capacity` correctness vs old `battery_ok or soc_recovered`: prove no real-world scenario regresses. Specifically: end-of-solar-day with no battery sensor at all (`reserve_soc=None`) — old code resumed, new code does not. Is that desired?
- Fill-priority resume on forecast decay: prove the `safety_margin_kwh` band prevents flap when `remaining_forecast_kwh` oscillates around `excess_solar_kwh_threshold`.
- Cross-rule precedence matrix (D2): for every pair of pause-sets (`_paused_by_us`, `_paused_by_grid_cap`, `_paused_by_battery_drain`, `_paused_by_arbitrage`, `_paused_by_fill_priority`, `_excess_solar_active`), is there a clear winner? Document in review output as a 6×6 matrix.

### Reviewer B — Async, lifecycle, restart resilience

**Mandate:** prove no race condition leaks state across HA restart, no orphaned task, no Bug Class #46 re-entrancy.

**Required deliverable:** lifecycle trace for `_pause_dispatch_ts` and `_observed_off_since_pause` across:
- Cold HA boot (EVPool `__init__`)
- EVSE add via config flow
- EVSE remove via config flow
- Smart-plug add / remove
- HA restart with active drain pause in flight (dispatch sent, response not yet received)
- HA restart mid-cooldown (cooldown expiry was monotonic — explicitly reset on init per D1 #9)
- Config flow re-edit triggering entry reload (does `EVPool.__init__` recreate the dicts? Yes — reset is safe per backlog memory decision.)

**Cross-checks:**
- Dispatch-latency races: HA fires `switch.turn_off`, state cache returns `is_on=True` for up to N seconds. URA's next decision tick reads stale state. Walk through with N=30s grace boundary — does the logic produce correct behavior at N=29, N=30, N=31?
- Emporia native solar mode auto-resume vs URA's 5-min tick: if Emporia turns the switch on 10s after URA dispatches off, URA's next tick (up to 5 min later) sees `is_on=True`, `observed_off=False` (never sampled the brief off state) → treats as auto-resume, re-pauses. Verify this is what `_observed_off_since_pause=False` semantics actually deliver.
- Bug Class #46: entity registry `async_update_entity` for the entity_id rename — is it called inside an options-flow step (forbidden) or at platform setup (OK)? Required: platform setup, once per entry, guarded by a flag in `entry.runtime_data` or similar.
- Timer/listener cleanup: no new timers in this cycle, but verify the NM trip's once-per-day edge detection doesn't leak a midnight reset timer.
- `RestoreEntity` vs reset semantics for the new `fill_priority_soc` Number — confirm the Number persists across restart via the existing URA Number RestoreEntity pattern (Bug Class #10 mitigation).

### Reviewer C — New surfaces + admin UX + cross-rule precedence

**Mandate:** prove every new user-facing surface round-trips cleanly and helper text accurately reflects behavior.

**Required deliverable:**
- Round-trip checklist for both Number entities (`excess_solar_soc`, `fill_priority_soc`): UI write → entry options → coordinator runtime attr → RestoreEntity persistence → restart → restored value.
- `unique_id` continuity proof: query entity registry before and after rename, confirm UUID unchanged.
- Legacy entity_id alias proof: confirm `switch.ura_energy_coordinator_excess_solar_charging` resolves via the registry's old_entity_id field for at least one release.
- Helper-text audit: each of the three helper-text strings (switch, force-charge button, per-EVSE checkbox) matches actual behavior per the spec above. No drift between docs/translations and code.
- 7 visibility attrs render check: instantiate `EVChargingStatusSensor` with a real `EVPool`, walk each attr, verify type and value.
- Cross-rule precedence matrix from Reviewer A — Reviewer C independently builds the same matrix and compares. Discrepancies surface ambiguity in the spec.

---

## Decision Tick Wiring (concrete diff target — `energy.py:2120-2220`)

Order after this cycle (insertions marked **NEW**):

```python
# Existing: pool optimization
# Existing: TOU EV (gated)
# Existing: arbitrage compound-load
# Existing: excess solar turn-ON (gated by self._excess_solar_enabled)
# Existing: grid import cap (gated)
# Existing: drain protection (D1 — modified, idempotent)
# NEW: fill-priority pause (gated by self._excess_solar_enabled — same switch)
if self._excess_solar_enabled:
    soc = self._battery.battery_soc
    remaining = self._battery.solcast_remaining
    fp_actions = self._ev.determine_fill_priority_actions(
        soc=soc,
        remaining_forecast_kwh=remaining,
        tou_period=period,
        soc_threshold=self._fill_priority_soc,
        excess_solar_kwh_threshold=self._excess_solar_kwh,
        safety_margin_kwh=DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH,
    )
    for action_spec in fp_actions:
        await self._execute_service_action(action_spec)
    # NM trip on rising edge — D4
    self._check_fill_priority_nm_trip(soc, remaining)
# Existing: power sensor health
# Existing: smart plug TOU
# Existing: smart plug drain (D1 — modified)
# NEW: smart plug fill-priority (same gate)
if self._excess_solar_enabled:
    sp_fp_actions = self._smart_plugs.determine_fill_priority_actions(
        soc=self._battery.battery_soc,
        remaining_forecast_kwh=self._battery.solcast_remaining,
        tou_period=period,
        soc_threshold=self._fill_priority_soc,
        excess_solar_kwh_threshold=self._excess_solar_kwh,
        safety_margin_kwh=DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH,
    )
    for action_spec in sp_fp_actions:
        await self._execute_service_action(action_spec)
```

`DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH = 1.0` (new constant in `energy_const.py`).

---

## LoC Estimate (validated against files)

| File | New LoC | Modified LoC | Notes |
|---|---|---|---|
| `energy_pool.py` | ~110 | ~50 | `determine_fill_priority_actions` × 2 (~60 + 35), state init expansion (~10), drain branch refactor (~25), `_prune_removed_evses` (~10), `get_status` expansion (~30) |
| `energy.py` | ~40 | ~15 | Decision tick wiring (~25), `_fill_priority_soc` accessor pair (~10), NM trip edge detection (~15) |
| `energy_const.py` | ~6 | 0 | Two new CONF keys, two new DEFAULT, one safety margin |
| `switch.py` | ~5 | ~5 | Factory call rename + unique_id_override |
| `number.py` | ~25 | ~5 | New `fill_priority_soc` Number, refresh helper on excess_solar_soc |
| `sensor.py` | ~30 | ~5 | 7 new attrs surfaced through `extra_state_attributes` |
| `button.py` | 0 | ~3 | Helper text refresh |
| `config_flow.py` | ~25 | ~10 | Per-EVSE checkbox + plug checkbox |
| `translations/en.json` + `strings.json` | ~20 | ~6 | New keys + revised excess-solar text |
| **Production subtotal** | **~261** | **~99** | |
| `test_energy_pool_drain.py` | ~220 | 0 | 9 named tests |
| `test_energy_pool_fill_priority.py` | ~140 | 0 | 7 named tests |
| `test_evse_solar_aware_ux.py` | ~100 | 0 | 9 named tests |
| **Test subtotal** | **~460** | 0 | |

**Production total: ~260 LoC new + ~100 LoC modified.** Within backlog estimate of ~200-280 LoC production.
**Test total: ~460 LoC new.** Above backlog estimate of ~400 LoC; difference is the explicit config-flow runtime smoke test + per-test docstrings.

---

## Pre-Deploy Zero-Bugs Gate (mandatory per user 2026-05-29)

Run from repo root **before** `./scripts/deploy.sh`:

```bash
# 1. Conflict markers
! grep -rn '^<<<<<<<\|^=======\|^>>>>>>>' custom_components/universal_room_automation/

# 2. Bytecode compile of every changed file
python3 -m py_compile $(git diff --name-only origin/master...HEAD -- 'custom_components/**/*.py')

# 3. Cycle test files
PYTHONPATH=quality python3 -m pytest \
  quality/tests/test_energy_pool_drain.py \
  quality/tests/test_energy_pool_fill_priority.py \
  quality/tests/test_evse_solar_aware_ux.py -v

# 4. Full suite (no new failures vs pre-review baseline)
PYTHONPATH=quality python3 -m pytest quality/tests/ -v --tb=line

# 5. Tag pre-review baseline (CLAUDE.md mandate)
git tag pre-review-v4.7.6 -m "Pre-review baseline for v4.7.6"
```

Any failure → STOP. Do not deploy.

---

## Post-Deploy Live Validation (Reviewer D)

Within 1 hour of HA restart:

1. **Entity presence:**
   - `switch.ura_energy_coordinator_evse_solar_aware_charging` exists.
   - `number.ura_energy_coordinator_fill_priority_soc` exists, value = 80 (or restored value).
   - `number.ura_energy_coordinator_excess_solar_soc` exists, value unchanged from pre-deploy.
   - `sensor.ura_energy_coordinator_ev_charging_status` exposes all 7 new attrs.

2. **Legacy entity_id alias:**
   - `switch.ura_energy_coordinator_excess_solar_charging` resolves (via registry alias) and shares state with the new entity.

3. **No errors in logs:**
   - `ha_get_logs(source="system_service", slug="core")` — no `ImportError`, no `TypeError`, no `KeyError` on EVPool / SmartPlugController.
   - No `Bug Class #46` re-entrancy warning during options-flow save.

4. **State machine quiescent on cold start:**
   - `pause_dispatch_state` attr is `{}` (no pending dispatches at boot).
   - `cooldowns` attr is `{}`.

5. **First real drain pause:**
   - Wait for an actual drain pause OR force one by setting a high SOC threshold via the Number entity.
   - Confirm `pause_dispatch_state.garage_a.last_dispatch` populated.
   - Confirm `observed_off` flips to `true` within 1-2 ticks.
   - Confirm no false cooldown.

6. **First fill-priority pause:**
   - Wait for natural conditions OR temporarily lower the `fill_priority_soc` to current SOC + 5%.
   - Confirm NM trip fires exactly once (informational LOW).
   - Confirm `pause_reason_human.garage_a` reads cleanly.

---

## Out of Scope (explicit non-goals)

- No DB schema change.
- No coordinator-level battery sensor source change (already Envoy per `energy_const.py:481`).
- No grid-import-cap behavior change.
- No EV TOU Management toggle scope change (still gates only `EVPool.determine_actions(period)` at `energy.py:2131`).
- No new arbitrage logic.
- No PWA / dashboard changes (consumed by v6.0.x cycle separately).
- No friendly-name vs entity-id zone scrambling fix for `sensor.ura_energy_coordinator_ac_ramp_state_*` — tracked in `project-ac-nudge-decouple-backlog`.

---

## Plan-Completion Tracking (skip / defer ledger)

Per `CLAUDE.md` mandate — every cycle must enumerate what was NOT done and why. This section is filled in by `ura-builder` at end-of-build before the cycle is declared complete. Template:

| Planned item | Status | Reason if deferred | Backlog ref |
|---|---|---|---|
| D1 — drain hardening | [PLANNED] | — | — |
| D1 — `SmartPlugController` mirror | [PLANNED] | — | — |
| D1 — `_prune_removed_evses` helper | [PLANNED] | — | — |
| D2 — `EVPool.determine_fill_priority_actions` | [PLANNED] | — | — |
| D2 — `SmartPlugController.determine_fill_priority_actions` | [PLANNED] | — | — |
| D2 — decision tick wiring | [PLANNED] | — | — |
| D3.1 — switch rename + unique_id pin | [PLANNED] | — | — |
| D3.1 — legacy entity_id alias | [PLANNED] | — | — |
| D3.2 — `number.fill_priority_soc` | [PLANNED] | — | — |
| D3.3 — `excess_solar_soc` helper-text refresh | [PLANNED] | — | — |
| D3.4 — per-EVSE `self_modulates` checkbox | [PLANNED] | — | — |
| D3.4 — per-plug `self_modulates` checkbox | [PLANNED] | — | — |
| D3.5 — Force-Charge button helper-text refresh | [PLANNED] | — | — |
| D4 — 7 visibility attrs on EV charging status sensor | [PLANNED] | — | — |
| D4 — NM trip on first fill-priority pause per day | [PLANNED] | — | — |
| D5 — 9 drain tests | [PLANNED] | — | — |
| D5 — 7 fill-priority tests | [PLANNED] | — | — |
| D5 — 9 UX/visibility tests | [PLANNED] | — | — |
| D5 — config-flow runtime smoke test | [PLANNED] | — | — |
| Tier 2-DB Review A | [PLANNED] | — | — |
| Tier 2-DB Review B | [PLANNED] | — | — |
| Tier 2-DB Review C | [PLANNED] | — | — |
| Live validation (Review D) | [PLANNED] | — | — |
| Post-review doc at `docs/reviews/code-review/v4.7.6_evse_solar_aware_review.md` | [PLANNED] | — | — |

**No items may be silently dropped.** If any row above ends in any status other than `[DONE]`, the cycle is not complete and the deferral must be explicitly accepted with a backlog reference.

---

## Recall keys

- "Resume v4.7.6 — EVSE Solar-Aware Charging"
- "Implement EV fill-priority + drain hardening"
- "v4.7.6 plan"
