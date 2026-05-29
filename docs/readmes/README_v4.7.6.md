# URA v4.7.6 — EVSE Solar-Aware Charging

**Release date:** 2026-05-29
**Tier:** Tier 2-DB (three parallel staff-engineer reviews, different framings — user-invoked outside formal trigger criteria because "this code has been full of correctness issues")
**Scope:** D1 drain rule hardening + idempotent re-pause + hybrid A+B `self_modulates`, D2 new `determine_fill_priority_actions`, D3 UX renames + new Number entity, D4 7 new visibility attrs + NM trip, D5 test coverage (Tier 2-DB regression discipline), D6 EVSE TOU unification + L1 plug visibility parity

**Trigger:**
- Live diagnostic post-v4.7.5 surfaced three compounding gate-logic bugs in EV/L1 pause behavior. The drain-rule resume condition (`battery_ok or soc_recovered`) caused URA's own pause to overflow solar into the battery, flipping `battery_ok` True, and URA immediately resumed EV — bouncing between paused and resumed mid-day.
- The manual-override branch (`energy_pool.py:553-561`) treated Emporia's native solar-mode auto-restart identically to a user gesture and set a 1-hour cooldown that suppressed both pause and resume, silently stuck EV ON.
- Existing drain rule only acted on active discharge; didn't pause when solar was fat enough to power EV plus trickle-charge battery, even though SOC was well below the user's preferred fill target.
- L1 plug TOU pause path was always-armed (no toggle gate), inconsistent with the rest of the cycle's L1 parallelism.

---

## Headline Changes

### D1 — Drain rule hardening + idempotent re-pause + hybrid A+B `self_modulates`

`EVPool.determine_battery_drain_actions` and `SmartPlugController.determine_battery_drain_actions` now:

1. **Drop the `if evse_id not in self._paused_by_battery_drain:` short-circuit on the pause action.** URA re-pauses idempotently every tick conditions are met. Mirrors the v4.7.x TOU pattern at `energy_pool.py:275-279`.

2. **Hybrid A+B `self_modulates` flag** (per-EVSE + per-plug config-flow checkbox, default `False`):
   - **Checked (Option A):** Smart EVSE / smart plug with native solar or schedule modes. URA is authority; idempotent re-pause every tick. Explicit user override is the EVSE Force-Charge button.
   - **Unchecked (default — Option B):** Manual-override detection via new state machine. `_pause_dispatch_ts` records when URA dispatched the pause. `_observed_off_since_pause` flips True when URA observes `state.is_on=False`. Manual-override branch only fires when ALL of: `evse_id in _paused_by_battery_drain`, `state.is_on=True`, `_observed_off_since_pause=True`, `monotonic() - _pause_dispatch_ts > 30s`. Catches real user toggles while ignoring dispatch latency and instant auto-resumes.

   Coverage matrix: smart EVSE + checked → A. Smart EVSE + unchecked → B auto-detects auto-resume as not-manual → still re-pauses. Dumb EVSE + unchecked → B correctly treats user toggle as override after grace + observed-off. Dumb EVSE + checked (misconfigured) → URA ignores override, re-pauses idempotently; user must Force-Charge.

3. **Refined `battery_out_of_capacity = battery_ok AND battery_soc <= reserve_soc + 2`** replaces the broken `battery_ok or soc_recovered` OR clause. Preserves end-of-solar-day intent (battery at reserve, capacity exhausted, grid taking over → resume EV) without the transient-equilibrium false positive that caused the v4.7.5-era bouncing.

4. **Reference-counted `_dispatch_owners: dict[evse_id, set[str]]`** (post-review fix-up A-H2/H3) prevents drain's resume handoff from clearing fill-priority's dispatch tracking and vice versa.

### D2 — New `determine_fill_priority_actions` (primary rule)

New gating method on both `EVPool` and `SmartPlugController`. PAUSE when: `tou_period != "peak"`, `soc < fill_priority_soc_threshold`, `remaining_forecast_kwh >= excess_solar_kwh`. RESUME when: `soc >= fill_priority_soc_threshold` OR `remaining_forecast_kwh < excess_solar_kwh - safety_margin`.

Tracking set `_paused_by_fill_priority`. Idempotent re-pause + hybrid `self_modulates` semantics shared with D1. Wired at `energy.py:_async_evaluate_dynamic_presets` decision tick right next to the existing drain check. Inverse-symmetric with `determine_excess_solar_actions` — both gated by the renamed `EVSE Solar-Aware Charging` switch.

### D3 — UX renames + new Number entity + helper text

- **Switch rename:** `switch.ura_energy_coordinator_excess_solar_charging` → `switch.ura_energy_coordinator_evse_solar_aware_charging` (entity_id changed, `unique_id` pinned to legacy slug for HACS history continuity). Friendly: "EVSE Solar-Aware Charging." One switch gates BOTH the existing excess-solar turn-on AND the new fill-priority pause.
- **New Number:** `number.ura_energy_coordinator_fill_priority_soc` (default 80%, min 50, max 95, step 5). Live-tunable. Existing `number.ura_energy_coordinator_excess_solar_soc` stays at 95% as the turn-ON threshold.[^excess-solar-soc-correction] Asymmetric thresholds: turn on at 95%, pause until 80%, generous middle band where neither rule fires and EV runs on TOU.

[^excess-solar-soc-correction]: Note (corrected 2026-05-29): `excess_solar_soc` was config-flow-only in v4.7.6; promoted to a live Number entity in v4.7.6.1. The functional rule in v4.7.6 worked correctly via `entry.options`; v4.7.6.1 just exposes the value as a live-tunable Number for parity with `fill_priority_soc`.
- **Per-EVSE + per-plug `self_modulates` checkboxes** in the energy config flow (post-review fix-up C-M2: conditionally exposed only for configured EVSEs/plugs).
- **EVSE Force-Charge button helper text updated** to reference the `self_modulates` flag and point to its config location.

### D4 — Seven new visibility attrs on `sensor.ura_energy_coordinator_ev_charging_status`

1. **`paused_by_fill_priority`** — list of paused EVSEs + L1 plugs (mixed keyspace).
2. **`pause_reason_human`** — per-device plain-English one-liners. Priority: fill_priority > drain > grid_cap > arbitrage > TOU > excess_solar > idle/charging/off.
3. **`cooldowns`** — `{expires, reason}` dict with LOCAL-tz formatting (`%z` numeric offset to survive HAOS tzdata gaps).
4. **`fill_priority_target_soc`** — echo of the current threshold.
5. **`fill_priority_solar_ok`** — bool reflecting the forecast-healthy gate state.
6. **`evse_config`** — `{self_modulates, source: "explicit"|"default"}` per device.
7. **`pause_dispatch_state`** — `{last_dispatch, observed_off, grace_expires}` per device. Lets you see exactly why the manual-override branch did or didn't fire on the last tick.

Plus a **once-per-day NM trip** (severity LOW, hazard_type `evse_fill_priority`, observation-mode gated at dispatch) on the empty→non-empty transition of `_paused_by_fill_priority`. Union of EV and plug sets (post-review fix-up B-H4).

### D5 — Test coverage (Tier 2-DB regression discipline)

Three new test files: `test_energy_pool_drain.py` (drain rule), `test_energy_pool_fill_priority.py` (new rule), `test_evse_solar_aware_ux.py` (UX surfaces + cross-rule). **79 cycle tests total.** Includes:

- The 9 plan-required test stubs (adversarial smart EVSE × explicit/default, dumb EVSE × observed-off variants, end-of-solar-day, transient equilibrium, etc.)
- N=5 adversarial loop fixture re-asserting `switch.garage_a = on` between URA dispatches
- Verification tests for every fixed HIGH (Force-Charge override across drain/FP/grid_cap/arbitrage on both pools; cross-rule dispatch-owner ref counting; per-plug `self_modulates` round-trip; NM trip union of EV + plug sets)
- Config-flow runtime smoke test (echoes the v4.7.4.2 zero-bugs-gate lesson)

### D6 — EVSE TOU unification + L1 plug visibility parity

User-coined principle mid-planning: "L1 plug is a smaller lower-voltage EVSE as much as possible."

- **`SmartPlugController.determine_actions(period)` now gated by `_ev_tou_enabled`** at `energy.py:2203`. Same toggle covers L2 and L1.
- **Switch friendly name:** "EVSE TOU Management" (was "EV TOU Management"). Entity_id `ev_tou_management` and unique_id unchanged for HACS history continuity. Helper text describes L1 + L2 scope.
- **L1 plugs surface as peer entries in `ev_charging_status`** with the same 6-key shape (`is_on`, `power`, `status`, `charging`, `power_source`, `energy_status`). Per-plug `assume_charging_when_on` flag (post-review fix-up C-M5) lets always-on idle plugs render `charging: False`.

---

## TL;DR

v4.7.6 closes three compounding EV/L1 pause bugs (drain resume bouncing, silent manual-override cooldown, never-pause when solar is fat), adds a new fill-priority gate symmetric with the existing excess-solar turn-on, splits the SOC threshold into asymmetric turn-on (95%) and pause-until (80%) Numbers with a generous middle band, unifies L1 plugs as first-class EVSE-class devices under one TOU toggle and one solar-aware switch, surfaces 7 new visibility attrs so the state machine is inspectable from a dashboard, and ships with 79 cycle tests + adversarial fixtures proving each fix.

---

## Review Trail (Tier 2-DB — three parallel reviewers, different framings)

**Reviewer A (correctness + state-machine invariants):** APPROVE WITH FIXES — 0 CRITICAL / 3 HIGH / 4 MEDIUM / 5 LOW / 3 INFO. State-machine table covered all 16 reachable cells of the 5-dimensional hybrid state. Identified Force-Charge contract violation across drain/FP/grid_cap/arbitrage (A-H1) and cross-rule shared-state clobber on dispatch handoff (A-H2/H3).

**Reviewer B (async + lifecycle + restart resilience):** APPROVE WITH FIXES — 0 CRITICAL / 4 HIGH / 7 MEDIUM / 5 LOW. Dispatch-latency walk at N=29/30/31s verified correct. Restart-resilience trace verified all transient state correctly resets at cold init. Identified dead code (B-H1), non-functional `runtime_data` migration guard (B-H3), NM trip ignoring SmartPlugController set (B-H4).

**Reviewer C (new surfaces + admin UX + cross-rule precedence):** APPROVE WITH FIXES — 0 CRITICAL / 3 HIGH / 6 MEDIUM / 7 LOW. Independent 6×6 cross-rule precedence matrix as cross-check of Reviewer A's matrix. Identified `pause_reason_human` "target None%" rendering (C-H1), single `l1_plug_self_modulates` violating per-plug intent (C-H2), missing helper text in strings.json (C-H3).

**Combined:** 0 CRITICAL across all three. 10 distinct HIGH findings (some overlapping across reviewers — strong signal). All HIGHs + 11 significant MEDIUMs addressed across three fix-up passes.

**Pre-Deploy Zero-Bugs Gate (all 4 gates pass at fix-up pass 3 HEAD):**
1. Conflict markers: clean
2. py_compile: clean across all changed `.py` files
3. v4.7.6 cycle tests: 79/79 pass
4. Full URA suite: 4197 passed / 55 failed / 14 errors — zero new regressions vs `pre-review-v4.7.6` baseline (4163 / 55 / 14)

---

## Backlog Spun Out During Cycle

- LOW-only deferrals from the three reviews (e.g., legacy `l1_plug_self_modulates` translation strings, dashboard `[object Object]` rendering risk on nested attrs, NM-trip DST consideration on the date token) — see plan §11 in `docs/planning/PLANNING_v4.7.6_evse_solar_aware_charging.md`.
- C-M3 partial: `evse_config` keyspace consistency locked via tests, but full keyspace unification across all 7 D4 attrs deferred to a future pass if dashboard layer requires it.
- Reviewer B's non-significant MEDs (B-M5 explicit logging on registry mutation failures, B-M6 narrower `except` in `ev_status` property) — both stable today, fix opportunistically in a future cycle.

---

## Carried Forward

- AC Nudge / AC Reset decouple ([`project_ac_nudge_decouple_backlog.md`](../../.claude/projects/-Users-okosisi-Code-universal-room-automation/memory/project_ac_nudge_decouple_backlog.md)) — split Gate 0 in `hvac_override.py:846` into `_ac_nudge_enabled` + `_ac_reset_enabled`; remove lockout side-effect on `daily_limit=0`. Adjacent: `ac_ramp_state` / `ac_ramp_last_action` sensor entity-id label scrambling. Surfaced during v4.7.5 live-validation.
