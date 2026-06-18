# MINI PLAN — Freeze (and overheat) safety response via heat_cool RANGE shift, not mode switch

**Status:** **CHOKEPOINT REVISION (2026-06-17) — supersedes the single-site FINALIZED DESIGN below.** The single-site floor (v5.5.4 build df→7eb38733) was Tier-3-reviewed: Review D found it LEAKS (pre-heat + override-compromise), Review A found a deadband-inversion bug, and an operator-directed full emission-path audit found **9 `set_temperature` sites** (all emit target_temp_low) across hvac.py / hvac_predict.py / hvac_override.py. Operator decision: build a **central chokepoint**, no blind spots, then Tier 3.

## CHOKEPOINT DESIGN (supersedes single-site)

**All 9 `set_temperature` emission sites (every one emits target_temp_low):**
1. `hvac.py:1533` preset-apply (resolved low) — 2. `hvac_predict.py:845` solar-bank restore — 3. `hvac_predict.py:915` solar-bank floor — 4. `hvac_predict.py:1053` pre-heat (`low+2`, D-HIGH) — 5. `hvac_override.py:873` override-compromise (D-MED) — 6. `hvac_override.py:1471` AC soft-nudge (passthrough `zone.target_temp_low`) — 7. `:1549` nudge restore — 8. `:1999` override restore — 9. `:2218` override restore (expired).

**Design:** one shared async helper `emit_set_temperature(hass, entity_id, target_temp_low, target_temp_high, *, freeze_active, blocking, ...)` in a NEW small module `hvac_setpoint.py`, importable by hvac.py / hvac_predict.py / hvac_override.py. It:
1. **Freeze floor:** `low = max(low, FREEZE_FLOOR)` when `freeze_active` and `low < FREEZE_FLOOR`.
2. **Deadband (fixes A-HIGH-1):** `high = max(high, low + MIN_DEADBAND)` so a raised low never inverts/violates the deadband.
3. Performs the `climate.set_temperature` service call (preserving each caller's `blocking` + any suppress() handshake the caller wraps around it).
ALL 9 sites refactored to call it instead of `hass.services.async_call("climate","set_temperature",...)` directly. `freeze_active` is owned by HC (`_update_freeze_active`) and read via a shared accessor (callable/ref the predictor + arrester already hold to the coordinator, or a small shared state object). No per-site clamps. Future setpoint writers inherit the floor.

**Out of scope (governed elsewhere):** `set_hvac_mode` writes (egress `off`, the v5.5.2 heat_cool enforcer, override reverts) — mode, not setpoint. `aggregation.py:3690` `set_preset_mode` — preset, not a low setpoint.

**Acceptance additions (beyond the single-site spec below):**
- **Verify the final emitted low ≥ 50 for EVERY site during a freeze** — including a full-cycle test where pre-heat runs AFTER the preset-apply (the D-HIGH repro): assert the *final* thermostat low ≥ 50.
- **Verify deadband:** a freeze + custom `cool_high=49` → emitted `(50, 52)` (or `low+MIN_DEADBAND`), never inverted.
- **Mutation:** neutering the chokepoint floor fails ≥1 test per emission class (preset, predict, override).
- **Review D (completeness) re-greps for a 10th `set_temperature` site** and confirms all route through the chokepoint.

---

**Status (original single-site, SUPERSEDED):** FINALIZED (Option B, 2026-06-17) — single-site floor. Kept below for history; the chokepoint above is the build.

---

## FINALIZED DESIGN (Option B — operator-approved 2026-06-17)

**One sentence:** an HC-owned freeze-protection **heat_low FLOOR** — when it's freezing outside, ensure each zone's heat_cool low bound is at least a pipe-safe floor (50°F); never touch anything else; auto-restore when it warms.

### Grounding (traced 2026-06-17, no assumptions)
- Preset ranges `(cool_high, heat_low)` live in `SEASONAL_DEFAULTS` (`hvac_const.py:354`). Winter away=(78,**60**), vacation=(80,**58**) → **normal presets already hold the house ≥58°F**, well above pipe-freeze. So the floor is a SAFETY NET, not new protection — it does nothing in normal operation and only catches a custom/edge preset set dangerously low.
- The current freeze response `_set_emergency_heat` (`hvac.py:1648`, triggered from `_handle_safety_hazard` `hvac.py:1598`) sets single-mode `heat` — and v5.5.2's heat_cool enforcer **reverts it next cycle**, so it's effectively a no-op today. Replace it.
- HC already has: live outdoor temp (`sensor.thermostat_bryant_wifi_*_outdoor_temperature`; the predictor's `_outdoor_temp_entity`), the `set_temperature` range-write path with arrester-suppression + idempotent "only write if range differs" (`hvac.py:1424-1461`, writing `resolved.cool_low`/`resolved.cool_high` → target_temp_low/high), and an existing cold-forecast eval (`preheat_forecast_low=35`).
- SC observation-mode switch reads `unknown` live; per operator SC is "not hardened enough to trust as a vector." So this is HC-owned and SC-independent.

### Behavior (v1)
- **Owner:** HVAC Coordinator. Evaluated each decision cycle inside the preset-apply / `set_temperature` resolution.
- **Context gate:** freeze active iff outdoor temp ≤ `FREEZE_TRIGGER_TEMP` (default **35°F**), with hysteresis (clear at **38°F**) to avoid boundary chatter. Read the best available outdoor temp (the predictor's configured `_outdoor_temp_entity`; fall back across the Bryant outdoor sensors). No outdoor temp available → do nothing (fail-open to normal presets; do NOT fabricate a freeze).
- **Action (floor clamp, the ONLY action in v1):** when freeze active AND a zone's resolved `heat_low` (`resolved.cool_low`) `< FREEZE_FLOOR` (default **50°F**), clamp it up: `cool_low = max(cool_low, FREEZE_FLOOR)`. If `heat_low ≥ 50` already (the normal case), NO-OP. The existing idempotent set_temperature write means no spam.
- **Auto-restore:** free — HC re-resolves the range every cycle; when outdoor recovers above 38°F, the next resolution is the normal preset. No timer, no "freeze-cleared" signal (the v5.5.0 no-blind-timer lesson).
- **Replace `_set_emergency_heat`:** remove the single-mode-heat freeze response (it's defeated by the enforcer anyway). The new floor IS the freeze response, and it's consistent with heat_cool ranges (the enforcer won't fight it).
- **Constants (hvac_const.py):** `FREEZE_FLOOR = 50`, `FREEZE_TRIGGER_TEMP = 35`, `FREEZE_TRIGGER_HYSTERESIS = 3` (clear at 38). Defaults tuned for Central TX (pipe-safe, non-aggressive); generalizable via config if later desired (not exposed in v1 — parsimony).

### Explicitly DEFERRED to a Safety-Coordinator-hardening follow-up (NOT in this cycle)
- **Faulty-thermostat detect-and-alert (Action 2):** a heat_low floor CANNOT rescue a thermostat lying about its `current_temperature` (it won't heat below its own false reading). The robust handling — cross-check an independent room temp sensor vs the thermostat, force an aggressive setpoint, AND alert the human — is a detect+alert feature that belongs in the Safety Coordinator (which the operator wants hardened). Tracked as its own cycle. Do NOT half-build it in HC.
- The SC freeze/HVAC-failure hazard as an additional OR-trigger — folds into that follow-up.

### Acceptance criteria (Tier 2-DB)
- **Verify:** with outdoor temp ≤ 35 AND a zone whose resolved heat_low < 50 → set_temperature writes target_temp_low=50; a zone whose heat_low ≥ 50 → NO write (no-op).
- **Verify:** outdoor temp > 38 → no clamp; the resolved range is the normal preset (byte-identical to pre-fix).
- **Verify:** hysteresis — once active at ≤35, stays active until > 38 (no boundary flap).
- **Verify:** no outdoor temp available → no clamp (fail-open), no crash.
- **Verify:** `_set_emergency_heat` removed; the freeze hazard handler no longer sets single-mode heat (and the heat_cool enforcer has nothing to revert).
- **Test:** behavioral tests driving the real preset-apply/resolution: clamp-fires, no-op-when-already-warm, no-clamp-above-trigger, hysteresis, missing-outdoor-temp fail-open. Mutation-anchored (deleting the clamp fails a test).
- **Live:** (winter / forced) — not live-exercisable in summer (outdoor 94°F); in-suite authoritative + a forced-config smoke check if feasible.

### Tier 2-DB review framings
- A: floor-clamp correctness + hysteresis + the `resolved.cool_low` injection point (right bound, right place) + no-op when ≥50.
- B: integration — replaces `_set_emergency_heat` cleanly; no fight with the v5.5.2 enforcer (floor keeps heat_cool); no fight with egress/AC-reset/away; fail-open on missing outdoor temp; restart.
- C: test authority (drive real resolution, mutation-anchored) + constant placement + parsimony (no over-exposed config) + confirm Action 2 is genuinely deferred (not half-built).

### Files (expected)
- `hvac_const.py` — `FREEZE_FLOOR`, `FREEZE_TRIGGER_TEMP`, `FREEZE_TRIGGER_HYSTERESIS`.
- `hvac.py` — clamp in the `set_temperature` resolution (~:1424-1461); remove `_set_emergency_heat` + its call in `_handle_safety_hazard` (~:1598); a small freeze-active helper reading outdoor temp with hysteresis state.
- tests — new behavioral file.

---

**Status:** QUEUED — bottom of the current ship list (after v5.5.2 heat_cool enforcer and the Arbitrage-WAIT floor fix). Operator-directed 2026-06-16.
**Tier:** 2-DB (Safety↔HVAC cross-coordinator; modifies the freeze hazard response — safety-adjacent).
**Branch (when built):** off `develop` AFTER the prior two fixes merge.

## Ship-list context (queue order + deconfliction)
1. **v5.5.2** — heat_cool enforcer + attain reason-string. (shipping)
2. **Arbitrage-WAIT floor** — `energy_battery.py` reserve_level sites. MUST branch off develop AFTER v5.5.2 (shares `_get_attainability_hold_decision`).
3. **Freeze-range (this plan)** — `hvac.py::_set_emergency_heat`. Independent of #2 (different file); complements #1 (retires the enforcer's "reverts single-mode heat" caveat). Branch after #1 (and after #2 for a clean linear develop).

## Problem it solves
`_set_emergency_heat` (`hvac.py:1648-1677`) responds to a freeze hazard by calling `climate.set_hvac_mode hvac_mode="heat"` (single-mode heat) on ALL zone thermostats. This is inconsistent with the operator's range-based operating model and with the v5.5.2 heat_cool enforcer — which now reverts single-mode `heat` back to `heat_cool` on the next decision cycle. The operator works via preset RANGES (heat_cool with low/high bounds), which are more energy-efficient and cover both heating and cooling. The Safety Coordinator is explicitly NOT trusted as a mode-switching vector.

## Goal
On a freeze hazard, keep zones in `heat_cool` but **raise the heat_cool LOW setpoint** so the range itself provides freeze protection (e.g. summer 70-75 → 75-80, i.e. low bound up to ~75°F so the thermostat heats anything below 75). No mode switch → the enforcer never has to fight it → consistent, range-based.

## Design (verify each against code before building)
- **Reuse the existing `set_temperature` path** at `hvac.py:1441-1467` — it already suppresses the OverrideArrester so a setpoint write isn't read as a manual override, and only writes when the resolved range differs (idempotent). The freeze response should set the range via THIS mechanism (or a small helper modeled on it), NOT `set_hvac_mode`.
- **Range source:** define a freeze-protection range (constant in `hvac_const.py`, e.g. `FREEZE_PROTECT_RANGE = (75, 80)` or a per-season offset). Operator's example: low ≈ 75°F. Confirm the exact bounds with the operator at build time.
- **Restore on clear:** when the freeze hazard clears, the zone returns to its normal preset range. NOTE the same gap the v5.5.2 review surfaced — there is **no "freeze cleared" signal** routed to HVAC, and the freeze hazard is **edge-emitted** (`safety.py:1698` `is_new` gate), so a sustained freeze does not re-emit. Decide the restore mechanism explicitly: (a) the normal `_apply_house_state_presets` range re-derivation will naturally restore the preset range each cycle UNLESS the freeze response is sticky — so if the freeze response simply biases the resolved range via a flag that clears when the hazard leaves `safety.active_hazards`, restoration is automatic; OR (b) a bounded hold. AVOID re-introducing a blind timer (the v5.5.2 A-CRITICAL-1 lesson). Prefer deriving freeze-active state from a trusted source at decision time — but per operator, the Safety Coordinator is "not hardened enough to trust as a vector," so the cleanest may be: the freeze response sets the elevated range once, and normal preset re-derivation restores it when conditions normalize. **Resolve this restore question with the operator before building** — it's the load-bearing design decision.
- **Overheat counterpart (optional, confirm scope):** there is currently NO HVAC response to overheat (≥100°F) — only freeze→heat and smoke/CO→fans. If desired, add a symmetric overheat range shift (lower the high bound). Out of scope unless operator asks.
- **All-zones vs affected-zone:** current code sets emergency heat on ALL zones. Confirm whether the range shift should be all-zones or only the hazard's location.

## Acceptance criteria
- **Verify:** a freeze hazard sets each zone's heat_cool range to the freeze-protect bounds via `set_temperature` (NOT `set_hvac_mode`); `hvac_mode` stays `heat_cool` throughout.
- **Verify:** the v5.5.2 enforcer does NOT fire on these zones (they're already `heat_cool`) — no fight, no flap.
- **Verify:** when the freeze clears, zones return to their normal preset range within one decision cycle, with NO blind timer.
- **Test:** behavioral test driving the freeze hazard → assert captured `set_temperature` (range) calls, assert NO `set_hvac_mode=heat`, assert restore on clear.
- **Live:** (winter / a cold snap, or a forced test) confirm the range shift holds and restores.

## Tier-2-DB review framings (when built)
- A: freeze-protection correctness — does the elevated low bound actually prevent freeze across thermostats; restore-on-clear has no stuck-state and no blind timer (the v5.5.2 lesson).
- B: Safety↔HVAC integration + suppress() handshake + no enforcer fight + restart resilience of any freeze-active state.
- C: test authority (drive real `_set_emergency_heat` / the freeze handler end-to-end, capture set_temperature; mutation-verify) + const placement + the all-zones-vs-affected decision.

## Open questions for the operator (resolve at build kickoff)
1. Exact freeze-protect range bounds (low ≈ 75°F? per-season?).
2. Restore-on-clear mechanism (automatic re-derivation vs explicit) — given Safety is not a trusted vector.
3. All-zones or affected-zone-only.
4. Add the symmetric overheat range shift, or freeze-only for now.
