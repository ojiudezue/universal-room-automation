# PLANNING — EVSE/L1 charge-onset (v3.1 — gated turn-on funnel, scoped to the live start paths)

Card: **EVSE-CHARGE-ONSET-TIME-1**
Status: PLAN (v3.1 — hardened after 2 framing-disjoint plan-reviews). Supersedes v1 (drain-release only — wrong/incomplete, backed out), v2 (ensure-on only — missed 6 paths), v3 (funnel, but pre-plan-review). **Tier 3** (4 framing-disjoint reviews) + this plan-review already done (A completeness + B build-prediction — both FIX-REQUIRED, all folded in here).

Operator directives (2026-08-31), binding:
- **Priority 0 (ship gate): the LIVE turn-on paths.** Empirically (`AUDIT_dp_live_behavior.md`: DP `TRANSITIONED`=0 over 21 nights) the operator's evening charging is **entirely the off-peak ensure-on** (#1 EVSE, #2 plug). DP reversion (#3) has never fired — kept as cheap latent insurance. The salvage already gates the drain-release sites (#4/#5) → kept, gated, for free. **P0 = #1,#2,#3,#4,#5.**
- **Priority 1 (attempt all, sacrifice individually if hard):** arbitrage (#6), fill-priority resume incl. its `forecast_decayed` dusk-grid leg (#10 + #10b), load-shed (#7), grid-cap (#11), `release_all_tou` (#12/#3-fallback). Route through the SAME funnel when clean; document any left un-gated. Never blocks the ship.
- **Turn-on ONLY.** No peer-owner added; no DP/drain/arbitrage/solar DECISION logic changed — only the turn-on emission is wrapped. The one whitelisted non-additive item is a pure refactor-extraction of `next_occurrence_of_hhmm` (see §6/B3).
- **Tier 3 + rigorous plan-review (done).** Record the design durably (D5).

## 0. Design in one paragraph (canonical)

A charger is turned ON by ~15 sites; there is **no single actuation site** (this defeated v1 and v2). v3 wraps the `switch.turn_on` emission in a **gated funnel** `_charge_on_or_defer(...)` that REFUSES the turn-on while the onset hold window is open; the **live/relevant charge-START paths route through it**, while escapes (must-start-by, force-charge) and true-solar (excess-solar) bypass. Completeness = the routed set; P0 covers the five that fire (or trivially could), P1 is best-effort.

## 1. The turn-on surface (canonical map — record in the manual, D5)

| # | Site | Path | Class | v3.1 |
|---|---|---|---|---|
| 1 | `energy_pool.py:1248` | EVSE off-peak **ensure-on** (2c) | START grid — **LIVE** | **P0 route + neuter test** |
| 2 | `energy_pool.py:3068` | Plug off-peak **ensure-on** (L1 Moes sockets) | START grid — **LIVE** | **P0 route + neuter test** |
| 3 | `energy.py:5234` | **DP reversion** (`_apply_dp_reversion`, direct async dispatch) | START grid — latent (never fired, audit) | **P0 inline guard + in-suite test** |
| 4 | `energy_pool.py:2032` | EVSE drain-release (`determine_battery_drain_actions`) | START grid | **P0 — salvage already gates it; route via funnel** |
| 5 | `energy_pool.py:3363` | Plug drain-release | START grid | **P0 — salvage already gates it; route via funnel** |
| 6 | `energy_pool.py:2454` | Arbitrage release | START grid (off-peak-gated) | P1 route-if-clean |
| 7 | `energy.py:7568/7663` | Load-shed release | START grid (rare) | P1 route-if-clean |
| 10 | `energy_pool.py:2271` | EVSE fill-priority resume — **`forecast_decayed` leg fires at DUSK on GRID** (NOT solar) | START grid | P1 route-if-clean |
| 10b | `energy_pool.py:3519` | **Plug** fill-priority resume (L1 twin of #10; same `forecast_decayed` dusk-grid leg) | START grid | P1 route-if-clean |
| 11 | `energy_pool.py:1767` | Grid-cap resume | situational | P1 route-if-clean |
| 12 | `energy_pool.py:2756/2800/2839`, `3120/3154` | `release_all_*` (toggle-OFF; also the `_apply_dp_reversion` **else-branch** when `_ev_tou_enabled=False`) | config/edge | P1 route-if-clean |
| 8 | `energy.py:5332` | **DP must-start-by** (`_apply_dp_must_start_release`, separate fn) | ESCAPE (03:00 liveness) | **BYPASS** |
| 9 | `energy_pool.py:1655` | Excess-solar (`determine_excess_solar_actions`) | SOLAR (true) | **BYPASS** |
| — | force-charge (`_force_charge_until`) | admin override | ESCAPE | BYPASS |

Corrections folded from plan-review A: #10b `:3519` added; fill-priority (#10/#10b) reclassified BYPASS→P1 (the `forecast_decayed` leg at `:2266`/`:3502` is an evening grid start, log `"resuming … (forecast decayed)"`); `release_all_tou` surfaced as #3's `_ev_tou_enabled=False` fallback.

## 2. Falsifiable invariant

**INV-ONSET-FUNNEL (v3 fix-up D-MED-1 wording):** when enabled and `now` is inside the hold window (`0 < onset_instant − now ≤ ONSET_MAX_HOLD_H`) and must-start-by not reached, the OVERNIGHT leg (`battery_out_of_capacity` at #4/#5) and the ensure-on/reversion emissions at #1/#2/#3 emit no `switch.turn_on` for an OFF charger. The DAYTIME leg (`daytime_release = soc_recovered`) is INTENTIONALLY ungated (baseline preservation): a solar-refilled battery must be free to share with the EV during daylight regardless of onset. Falsified only by an overnight-leg tick that turns an off, enabled charger ON.

- **INV-NO-INTERRUPT:** funnel only withholds a turn-on for an already-OFF charger; never emits `turn_off`. (Consequence: a charger started early via an un-routed P1 path is left running — accepted per scope.)
- **INV-ESCAPE:** #8 must-start-by + force-charge always turn on (bypass). Defaults (onset 01:00 < 03:00) → escape never binds; the bounded 8h window alone releases at 01:00 (L1 anti-stranding, restart-safe).
- **INV-BASELINE:** enable OFF / blank / malformed onset / `now is None` → P0 sites byte-identical to develop.
- **INV-TURN-ON-ONLY:** change confined to the funnel + the P0 turn-on emissions + additive enable/time/observability wiring + **the whitelisted pure extraction of `next_occurrence_of_hhmm`** (B3). No pause-owner added; no DP/drain/arbitrage/solar DECISION logic changed.

## 3. Deliverables

### D1 — the gated funnel (exact signature; no fabricated attrs — B1/B2)
```python
def _charge_on_or_defer(self, evse_id, switch_entity, now, enabled,
                        onset_str, must_start_by_min, *, bypass_onset=False):
    """Return [turn_on action] OR [] + mark evse_id onset-deferred.
    `now` = tz-aware LOCAL dt (dt_util.now()); None ⇒ permit (fail-open).
    `must_start_by_min` threaded from coord `_dp_must_start_by_min` (int|None).
    Logs permit vs defer with distinct strings (defer names onset + release instant). — B7"""
    if not bypass_onset:
        onset_permits, must_start_by_reached = _evaluate_onset_gate(
            now, enabled, onset_str, ONSET_MAX_HOLD_H, must_start_by_min)
        if not (onset_permits or must_start_by_reached):
            self._onset_deferred.add(evse_id)
            _LOGGER.info("charge-onset: deferring %s until onset %s", evse_id, onset_str)
            return []
    self._onset_deferred.discard(evse_id)
    return [{"service": "switch.turn_on", "target": switch_entity, "data": {}}]
```
- **`now` (B2):** funnel receives a LOCAL tz-aware `dt_util.now()` (HH:MM onset is wall-clock; UTC is wrong). `now is None` ⇒ permit.
- **`must_start_by_min` (B1):** an explicit arg, NOT `self._must_start_by_min` (which does not exist). EVSE `determine_actions` already has `coord` → `getattr(coord, "_dp_must_start_by_min", None)`. **Plug `determine_actions` has no `coord`** → add a `must_start_by_min: int|None = None` kwarg (mirroring the salvage's `determine_battery_drain_actions` kwarg) and thread it from the coord call site `energy.py:6155`; EVSE call site `energy.py:6630`.
- **enabled/onset_str:** the controller instance attrs `self._ev_charge_onset_enabled` / `self._ev_charge_onset_time` (set by the fan-out setters, D3).

### D2 — route the P0 sites
- **#1 EVSE ensure-on `:1248`, #2 plug ensure-on `:3068`:** replace `if not is_on: actions.append({turn_on})` with `if not is_on: actions.extend(self._charge_on_or_defer(...))`. **Keep the bookkeeping (`_proactive_offpeak_holds.add`, `_paused_by_us.discard`) OUTSIDE the `if`, unchanged** (`:1264-1265` / `:3075-3076`) — the funnel never reads switch state (B7-cleared). **Move the "proactive off-peak turn-on" log INTO the funnel** so a refused turn-on doesn't mislog (B7).
- **#4 EVSE drain-release `:2032`, #5 plug drain-release `:3363`:** the salvage already gates these inside `determine_battery_drain_actions` (`e5a90e4fb:energy_pool.py:2210`/`:3619`). **Keep them, re-expressed through the funnel** for one gate path. Extend INV + the neuter table to all 5 sites (B5).
- **#3 DP reversion `energy.py:5234` (B8 — exact ordering):** insert the guard **after `:5230`** (the `_paused_by_dp.discard` + `_release_pause_dispatch_owner` already done — do NOT `continue` before them; the H-2 sticky machinery depends on that order), wrapping **only** the `if not state.get("is_on"):` dispatch block. On hold: `self._ev._onset_deferred.add(evse_id)` and fall through to the next loop iteration. `self` is `EnergyCoordinator`, so `self._dp_must_start_by_min` (`:368`), `self._ev._ev_charge_onset_enabled/_time` are in scope; compute `now = dt_util.now()` locally. **No new args threaded.** (Live criterion is in-suite-only — #3 never fires, A-MED-2.)

### D3 — enable toggle + time entity + observability (salvage + all prior CRIT fixes carried — verified complete by plan-review B)
Reinstate from the salvage stack (see §6): bespoke enable switch routing through `set_ev_charge_onset_enabled`; both CONF keys in `_EC_SETTER_DISPATCH` AND `OPTIONS_RELOAD_SUPPRESS_KEYS`; `Platform.TIME` on `INTEGRATION_PLATFORMS` (CM-forwarded); entities re-read options on `SIGNAL_ENERGY_ENTITIES_UPDATE`; seconds-tolerant `_parse_hhmm`; D-LOW-3 getter reads own field.
- **`_onset_deferred` is TWO independent sets** (one per controller). **Reset (B6):** discard `evse_id` at the top of each off_peak branch AND on the `is_on` path, so the set can't latch ON after the charger starts. Add `_onset_deferred` cleanup to `_prune_removed_evses` (EVSE) and `prune_removed_plugs` (plug).
- `binary_sensor.ura_ev_charge_onset_active` = **union of both** controllers' `_onset_deferred`; note on the sensor it's only meaningful for chargers that reach a routed site (a DP/blind-window `continue` upstream leaves it empty).

### D4 — knobs
`ONSET_MAX_HOLD_H = 8.0` (module const, rung-1); `CONF_ENERGY_EVSE_CHARGE_ONSET_TIME` (TimeSelector + time entity, default "01:00"); `CONF_ENERGY_EVSE_CHARGE_ONSET_ENABLED` (bool + switch, default set at operator checkpoint); reused `CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT` (escape).

### D5 — DESIGN RECORD (operator-mandated; part of "done")
Propagate the §1 map + funnel design + route/bypass classification into: `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` (new "Charge-onset & the turn-on surface" section); `docs/reviews/URA_CODE_TRACING_METHODOLOGY.md` ("who turns the charger on" = ~15 sites, none singular; cite the map); memory `project_charge_onset_correct_site` (funnel design + P0 set); skill `ura-energy-invariants-campaign` (add the turn-on-site enumeration to its Phase-1 greps). Forcing function so no future agent re-excavates.

## 4. Acceptance criteria — DISCRIMINATING + per-site neuter
- **INV-ONSET-FUNNEL per P0 site #1,#2,#4,#5:** OFF charger, enabled, onset 01:00, now 22:00 → no turn_on; **neuter** (route that site directly to turn_on) → NAMED test RED. **#3** same but in-suite-only (never fires live — cite `AUDIT_dp_live_behavior.md`).
- **Clamp discriminator (B4):** onset 01:00, `must_start_by_min=720` (12:00), now 17:30 → `must_start_by_reached` must be **False** (hold holds). On the UN-clamped salvage helper this is True (hold defeated every tick) → the test is RED on the un-clamped `ms_ref`. This pins B4.
- **Boundary:** now 01:00 → releases; now 10:00 (delta 15h > 8h) → releases.
- **CROSS-MIDNIGHT (named test, the operator's scenario):** drain at 22:00 **day 1**, onset 01:00. Assert HELD at 22:00 day1, 23:59 day1, AND **00:30 day 2 (past the date rollover)**; assert RELEASE at exactly 01:00 day 2. Proves `next_occurrence_of_hhmm` carries the hold across the date boundary (the delta is computed to the *next* occurrence, which is day 2). Also assert the must-start escape at 22:00 day1 resolves its 03:00 deadline to **day 2** (03:00 day2) and does NOT bind (onset 01:00 < 03:00). Mutation: replace `next_occurrence_of_hhmm` with a same-day `now.replace(hh,mm)` (no day-rollover) → this test goes RED at the 00:30-day2 / 22:00-day1 ticks. Reuses the existing `compute_must_start_by` day-boundary primitive (verified byte-faithful extraction, develop `energy_drain_precedence.py:356`).
- **INV-NO-INTERRUPT:** `is_on` charger inside window → no `turn_off` at any routed site.
- **INV-ESCAPE:** #8 must-start turns on regardless (bypass, separate fn); onset > 03:00 documented inert from 03:00.
- **INV-BASELINE:** enable OFF → all 5 P0 sites byte-identical (mutation: force enabled=True → RED).
- **INV-TURN-ON-ONLY:** `git diff develop` touches only funnel + 5 P0 emissions + additive wiring + the `next_occurrence_of_hhmm` extraction; DP/drain/arbitrage/solar decision logic byte-identical.
- **`_onset_deferred` reset:** a charger deferred at 22:00 then started at 01:00 → sensor clears (mutation: remove the reset → sensor latches → test RED).
- **Live:** off-peak evening before 01:00, enable ON → garage_a/b + Moes L1 sockets stay OFF, turn ON at 01:00; enable OFF → start immediately.

## 5. Non-goals
- No new peer pause-owner; no change to `_stronger_peer_holds` / precedence tuples.
- No change to DP/drain/arbitrage/load-shed/excess-solar DECISION logic — only the turn-on emission at routed sites is wrapped.
- P1 (#6,#7,#10,#10b,#11,#12) best-effort; sacrifice an individual P1 only if hard; document it; never expand beyond turn-on.
- Never turn a charger OFF for onset. No plug-tier DP participation.

## 6. Salvage (exact source — B3/B4)
The onset surface is a **3-commit stack** on the deleted branch (all reachable by SHA): `20ff45402` (Rev-5 base: consts, `DEFAULT_*`, `time.py`, `strings.json`/`en.json`, config-flow field, `binary_sensor` gate-open, `sensor` over-hold, **and the `next_occurrence_of_hhmm` extraction in `energy_drain_precedence.py:356` refactoring `compute_must_start_by` to delegate**) → `4e15a157b` → `e5a90e4fb` (Rev-6 delta). **Salvage base = `git diff 1d9749810...e5a90e4fb`** (merge-base verified) or per-file `git show e5a90e4fb:<path>` — NOT `git show e5a90e4fb` (that shows only the Rev-6 delta and silently drops the Rev-5 base). Required benign extraction: `next_occurrence_of_hhmm` (does not exist on develop; whitelisted in INV-TURN-ON-ONLY).

**The `_evaluate_onset_gate` helper — use THIS text (clamped), NOT the salvage text** (salvage `e5a90e4fb:energy_pool.py:162` has the un-clamped `ms_ref` — B4):
```python
def _evaluate_onset_gate(now, enabled, onset_str, max_hold_h, must_start_by_min):
    """(onset_permits, must_start_by_reached). enabled False / bad onset / now None ⇒ (True, False)."""
    if not enabled: return True, False
    parsed = _parse_hhmm(onset_str) if onset_str else None
    if parsed is None or now is None: return True, False
    oh, om = parsed
    from datetime import timedelta as _td
    from .energy_drain_precedence import next_occurrence_of_hhmm
    onset_instant = next_occurrence_of_hhmm(now, oh, om)
    delta_h = (onset_instant - now).total_seconds() / 3600.0
    in_hold_window = 0 < delta_h <= float(max_hold_h)
    onset_permits = not in_hold_window
    must_start_by_reached = False
    if in_hold_window and must_start_by_min is not None:
        ms_hh, ms_mm = divmod(int(must_start_by_min), 60)
        window_start = onset_instant - _td(hours=float(max_hold_h))
        ms_ref = max(now - _td(hours=float(max_hold_h)), window_start)   # B4 clamp
        ms_instant = next_occurrence_of_hhmm(ms_ref, ms_hh, ms_mm)
        must_start_by_reached = now >= ms_instant
    return onset_permits, must_start_by_reached
```
Description corrections (match code): it is a **bounded pre-onset window**, NOT "overnight-only"; the must-start escape **never binds at defaults** and any onset > 03:00 is inert from 03:00 (so onset should be ≤ the must-start minute to be meaningful — state on the knob). Carry the prior CRIT fixes verbatim: enable-switch routes through `set_ev_charge_onset_enabled`; both CONF keys in `_EC_SETTER_DISPATCH` + `OPTIONS_RELOAD_SUPPRESS_KEYS`; `Platform.TIME` on `INTEGRATION_PLATFORMS`.

## 7. Tier / review
Tier 3. Plan-review DONE (A + B, folded in). Build → 4 framing-disjoint reviews (A local-correctness/helper-math incl. the clamp; B lifecycle/wiring/CRIT-carryover; C test-authority via per-site neuter of all 5 P0 sites; D adversarial-completeness: enumerate the WHOLE turn-on surface, prove each un-routed path is a documented-accepted leak not an unnoticed one, and that no bypass path was accidentally gated). Orchestrator independent mutation-verify of the 5 P0 sites before ship. **Operator checkpoint before deploy** (enable default ON/OFF is the operator's call).
