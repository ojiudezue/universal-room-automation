# PLANNING — EVSE day/night-aware fill-priority release (EVs charge overnight)

**Status:** PLAN — awaiting operator go-ahead.
**Tier:** 3 (EV/TOU pause-ownership; regression-prone; day/night-boundary; the #15/#16 pause-collision history). 4 framing-disjoint reviews + completeness pass + mutation-anchored day/night behavior + live validation.
**Branch (when built):** `feature/evse-offpeak-fill-release` off develop.

## Problem (diagnosed, code + live grounded 2026-06-18)
EVs never complete a charge — "good at pausing, bad at starting." Root cause: **fill-priority holds the EVs while a solar signal that is high all night says so, and never releases at the off_peak boundary.**
- Fill-priority HOLD = `soc < fill_priority_soc(80) AND forecast_healthy` (`energy_pool.py:1139-1143`); RELEASE = `resume_soc_met OR forecast_decayed` (`:1144, 1232`). It special-cases only `peak` for release (`:1128-1137`).
- `forecast_healthy` = `solcast_remaining ≥ 5 kWh` — but `solcast_remaining` is "remaining **today**," which after midnight rolls to the full next-day forecast (~140 kWh). So at 2am `forecast_healthy=True` → permanent overnight hold. Live proof 02:23 CDT / off_peak: `pause_reason_human: "holding for battery fill (target 80%, solar healthy)"`, all 4 chargers held.
- The off_peak ensure-on (`energy_pool.py:528-570`, which should start charging on cheap grid) hits a carry-over guard at `:560` — if the EV is in `_paused_by_fill_priority` it `continue`s and never turns the charger on. **Deadlock.**

## PHASE INVARIANT — TIME-anchored, never inferred from instantaneous solar (operator, 2026-06-18)
The EV charge day/night PHASE (hold-for-fill vs release-for-grid) is determined by **TOU period + the day-boundary lookahead (`peak_ahead_before_offpeak`) + sun/daylight bounds — i.e. TIME, never instantaneous PV / battery-power state.** Rationale: on a cloudy/rainy DAYTIME, PV ≈ 0 and the battery may be idle — the state "seems limpid" (looks like night) but it is still daytime with mid_peak/off_peak boundaries near. Inferring "night → release the EVs" from low PV would wrongly start charging during expensive mid_peak. The fixed TOU rate schedule does not move with clouds, so TIME is the robust signal.
- **D1 release** uses `tou_period` + `peak_ahead_before_offpeak` ONLY (no solar input) → inherently cloud-proof.
- **D2's "is solar replenishing" refinement** uses a TIME-WINDOWED, load-netted solar signal — REUSE **`_expected_solar_surplus_pct`** (energy_battery.py, the FIN-2 inclement primitive: forecast × daylight-overlap × capture-factor, nets house load), which returns ~0 at night and real-but-low on a cloudy daytime. **BANNED: raw `solcast_remaining` ("remaining today")** — it is high all night and IS the original bug. Live `battery_power > 0` (actively charging) is an acceptable secondary "solar present now" check.
- A cloudy daytime is still DAYTIME (hold for the fill window); only the actual off_peak window releases for grid charging.
This is a hard review axis (Reviewer A/D): any solar/PV input used to make a PHASE decision must be time-anchored; flag any instantaneous-PV-as-night-proxy.

## Operator's vetted intended design (the spec)
1. Fill-priority's 80% target is **daytime peak-rate protection** — during the day, fill home batteries first, then charge cars; cars must not pull expensive mid_peak/peak grid.
2. **Never discharge the battery into the EV** — charge from solar or cheap (off_peak) grid only. *(Already correctly implemented by the battery-drain gate — discharge-aware, not a blind clamp.)*
3. After peak ends (~8pm summer), the 80% clamp **disappears**; once the battery is at reserve, **fire the chargers on cheap off_peak grid** (~9pm–3am).
4. EVSE logic must be **day/night-boundary + TOU aware**.

## Institutional context verified (reuse, don't reinvent)
- **`energy_tou.py` primitives** (REUSE): `get_current_period(now)` `:165`; `peak_ahead_before_offpeak(now)` `:247` (midnight-safe "is a real peak still ahead before the next off_peak"); `get_next_transition` `:199`.
- **Reference implementation = the battery strategy** (`energy_battery.py`): holds for peak, releases at off_peak, gates mid_peak holds on `peak_ahead_before_offpeak(now)` (`:2240/2883/2912`), cross-midnight-safe via `_classify_target_day` (`:944-1003`). This is the exact day/night rhythm fill-priority must mirror.
- **`tou_period` already plumbed** into `determine_fill_priority_actions(tou_period, ...)` (`energy_pool.py:1082`) and the EV controller (`:450/499/528`) and battery-drain (`:1304/1416`). No new plumbing.
- **`_tou` reference** available on the controllers (used by the EV TOU pause at `:499`). `peak_ahead_before_offpeak` is callable from the pool if the `_tou` ref / `now` is available at the call site — VERIFY at build (the fill-priority call site `energy.py:2692-2699` passes `tou_period`; confirm `now`/`_tou` reachable or thread them).
- **Prior-art greps:** no existing `off_peak` release in fill-priority (the gap); `_paused_by_fill_priority` ownership set is dedicated (no #15/#16 collision); battery-drain is a separate dedicated set.
- **Memory pulled:** EV off-peak cycle (v4.7.28 ensure-on), day-boundary TOU (v4.7.29, Bug Class #51), the "solar-first; never drain battery into car; off_peak grid cheapest" durable principle, the #15/#16 pause-ownership collision class.

## Deliverables

### D1 — Fill-priority becomes day/night-aware (release at off_peak / post-peak)
Make fill-priority **inert outside the daytime pre-peak fill window**, mirroring the battery strategy:
- `peak` → release (existing, unchanged).
- **`off_peak` → release** (NEW): clear `_paused_by_fill_priority`, do NOT re-hold. off_peak is the cheap-grid window; EVs should charge.
- **`mid_peak` → hold ONLY IF `self._tou.peak_ahead_before_offpeak(now)`** (NEW): i.e. hold only when a real peak is still ahead before the next off_peak (daytime fill window protecting that peak). In post-peak mid_peak (no peak ahead), release. Direct reuse of the battery's `:2240/2883` pattern.
- Net: fill-priority = "daytime, before-peak battery-fill protection," releasing for the night cheap-grid window. The 80% daytime target is UNCHANGED.

**Acceptance:**
- **Verify:** off_peak with EV connected → `_paused_by_fill_priority` cleared and the off_peak ensure-on turns the charger ON (live: `paused_by_fill_priority: []` overnight; charger goes Charging).
- **Verify:** mid_peak with a peak ahead → still held (daytime fill protected). Post-peak mid_peak (no peak ahead) → released.
- **Verify:** daytime pre-peak fill behavior byte-identical (80%-before-cars unchanged) when a peak is ahead.
- **Test:** drive `determine_fill_priority_actions` across {peak, mid_peak+peak_ahead, mid_peak+no_peak_ahead, off_peak} × {soc<80, soc≥80} — assert release/hold per the matrix. Mutation: removing the off_peak release re-deadlocks (a test fails). Cross-midnight: a 23:00→05:00 off_peak window releases throughout (no midnight re-lock).
- **Live:** EVs charge overnight (the headline — confirm a real off_peak session starts and persists).

### D2 — Solar-gate battery-drain's high-SOC release (guarantee overnight grid-charge; the wear benefit)
**CORRECTED 2026-06-18 (operator):** battery-drain is NOT to be released "in off_peak." It is the GUARANTOR of grid-charging and is mostly correct as-is — its `battery_out_of_capacity` release (`SOC ≤ reserve_soc + 2`, `energy_pool.py:1023-1028`) IS the intended "wait until the battery has drained to reserve, then the EV charges from guaranteed grid" mechanism. Do NOT change that; do NOT add a blanket off_peak release (that would let the EV drain the battery before reserve — the opposite of intent).

**The one flaw:** the *other* release `soc_recovered = SOC ≥ soc_threshold + 5 (=85)` (`energy_pool.py:1029-1032`) is a **daytime-solar assumption** ("solar recharged the battery, the EV can share"). At night (no solar) it is wrong: at 85% with no solar, it releases and the EV drains the battery (~85→79, a house load with no solar = battery discharge) until soc_low re-pauses — exactly the high-L2-rate battery wear to avoid, and not guaranteed grid.

**Fix:** make `soc_recovered` SOLAR-AWARE — only allow the high-SOC release when solar is **actively replenishing** the battery (daytime, battery charging / a near-term solar signal that is genuinely ~0 overnight — NOT `solcast_remaining`, which is the v5.5.3 trap). At night / no solar, the ONLY release is `battery_out_of_capacity` (reserve). Reuse the same near-term-solar discrimination chosen for D1's forecast signal (keep them consistent). Net: overnight EV charging is reserve-gated → guaranteed grid + less battery wear; daytime solar-sharing behavior unchanged.

**Why grid-vs-battery can't be source-tagged (the governing principle):** the EV is a house load; you cannot distinguish "EV from grid" vs "EV from battery discharge." The ONLY guarantee that the EV draws from grid is `battery == reserve` (battery won't discharge below reserve → added load is grid-served). So the overnight release MUST be reserve-gated, not off_peak-gated.

**Acceptance:**
- **Verify:** night/no-solar, battery at 85% → battery-drain holds the EV (no `soc_recovered` release); it releases only when the battery drains to reserve (`battery_out_of_capacity`) → EV then charges from grid. Daytime with solar actively charging the battery at 85% → `soc_recovered` releases (EV shares solar) — unchanged.
- **Verify:** the "never discharge battery into EV" invariant holds across day/night: an EV charge never pulls the battery below reserve, and never drains a high-SOC battery at night.
- **Test:** {day+solar vs night/no-solar} × {SOC at 85 vs at reserve+2 vs mid} matrix; assert reserve-only release at night, solar-release allowed by day. Mutation-anchored (removing the solar gate lets the night-85 case wrongly release).

### D3 — Verify ensure-on precedence + no oscillation
After D1/D2, confirm the off_peak ensure-on (`:528-570`) fires (no longer vetoed by a stuck `_paused_by_fill_priority`), and there's no tug-of-war between owners at the off_peak boundary (the resume-handoff chains `:559/755/849` settle cleanly). No double-emit, no flap at the period transition.

**Acceptance:** Verify at the mid_peak→off_peak transition the EV transitions paused→charging once and stays (no oscillation). Test the handoff. Live: a clean single transition.

## Tier 3 review framings
- **A — fill-priority release correctness + the peak_ahead_before_offpeak reuse** (right primitive, midnight-safe, the {period × soc} matrix).
- **B — battery-drain off_peak awareness + the "never discharge battery into EV" invariant preserved** for the genuine daytime-no-solar case (the safety/cost invariant must not regress).
- **C — test authority** (drive real `determine_*_actions` end-to-end; per-case mutation; cross-midnight; no tautology) + the daytime byte-identical guarantee.
- **D — completeness / adversarial:** is there ANY other gate or path that still holds the EV overnight after D1/D2 (the audit found fill-priority + battery-drain; are there others — grid-cap, arbitrage, a fourth owner)? Re-enumerate every `_paused_by_*` set's off_peak behavior. Confirm no remaining overnight blocker.

## NON-GOALS / out of scope
- Not changing the 80% daytime target (it's the operator's intended fill target; correct as-is).
- Not adding new config knobs (reuse existing).
- Not touching arbitrage/attain (that's the battery's domain; this is EV pause/resume).

## Live validation plan
Post-deploy, overnight: confirm at the mid_peak→off_peak boundary (~8pm summer) fill-priority clears, the chargers start on off_peak grid, and the EVs reach a real state of charge by morning — with the battery NOT discharged into the cars (battery stays ≥ reserve, EV source = grid). Recorder + the EV diag sensor (`paused_by_fill_priority` should be `[]` overnight).
