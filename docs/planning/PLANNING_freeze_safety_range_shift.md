# MINI PLAN — Freeze (and overheat) safety response via heat_cool RANGE shift, not mode switch

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
