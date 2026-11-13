# Plan review: PLANNING_hvac_precool_standdown_and_seasons.md (Tier 2, one adversarial pass)

Branch `plan/hvac-precool-standdown` @ `25b8b341`. Reviewer read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`
completely first; nothing in its §10 ledger is re-asserted. Every claim below was re-checked by grep/read on the branch.

**Verdict: FIX-PLAN.** The core design (start-time skip inside `_execute_zone_pre_cool`, thermostat reading, caller-side
season gate, no "end on reached target") is right. One MEDIUM is a real wasted-write path the plan does not cover; two
MEDIUMs are a wrong episode key and a trip-wire that cannot discriminate. Fix those in the plan, then build.

## Findings (ranked)

### M1 — Master-OFF release writes a raw baseline setpoint (a Carrier manual hold) on a stood-down zone. Bug class #53 (one missed site)
- The caller adds every pre-arrival zone to `_pre_conditioning_zones` whatever the pre-cool did
  (`hvac_predict.py:706-707`); that set becomes `_last_pre_conditioning_zones` (`:738`).
- When switch 28 flips OFF, `release_set = _last_pre_conditioning_zones | _last_precool_zones` (`:486-488`). A stood-down
  zone has no token, so it is not in `_pa_rel` (`:493-496`) and goes to `_release_banked_zones(release_set)` (`:509`).
- In `_release_banked_zones`, no token → `_s11_pre_preset = None` (`:1040`) → Carrier `is_human_manual_snapshot(None)` is
  True (`hvac_strategy.py:790`) → the raw-setpoint branch writes the baseline with `set_temperature` (`:1072+`), which
  puts the Carrier zone into a manual hold on a zone that never borrowed.
- Repro: house `home_day`, zone_2 thermostat at 74, a pre-arrival trigger; the stand-down skips (74 ≤ 75); the operator
  turns `28 · HVAC Predictive Conditioning` off inside the 20-minute window → one S11 raw write.
- This is pre-existing for zones skipped by the setpoint compare (`:1299-1300`) and for D2's `off_season` skip. The
  stand-down raises it from rare to about half of arrivals.
- **Fix in plan:** add a deliverable line and a test: a zone with no banking token in `release_set` writes nothing
  (skip it in `_release_banked_zones`, or keep stood-down/off-season zones out of the release set). Re-check that
  `sensor.ura_hvac_pre_arrival_status` / zone presence labels do not depend on that set before choosing.

### M2 — "One activity row per (zone, arrival episode), keyed on `_pre_arrival_start`" does not key an episode
- `_pre_arrival_start[zone_id] = now` is overwritten on EVERY repeat trigger (`hvac.py:7249`). The plan's own fire check
  shows 201 intake rows against 45 borrows in November, so a single arrival produces several triggers and several rows.
- `_pre_arrival_start` lives on `HVACCoordinator`, not the predictor. The predictor would read it through `_hvac_coord`.
- **Fix in plan:** key on zone membership instead. Keep a per-zone "stand-down logged" flag that is cleared when the zone
  leaves `_pre_arrival_zones` (arrival / timeout / max age / spend). Test it with two triggers in one window: one row.

### M3 — D4 trip-wire cannot tell a fault from the weather, and it pages HIGH
- "Zero stand-downs in 7 days" is the normal summer state, because zones are hot on arrival. "Zero writes" is a normal
  mild-shoulder state, because every zone is cool. Both alarms fire in legitimate conditions, at HIGH (which reaches
  the companion channel), up to once a week. The NM text that says "or the weather turned hot" admits the problem.
  This fails the CLAUDE.md corollary that an observation must discriminate.
- The stand-down's failure direction is safe. With T None it falls back to the legacy write, and a wrongly-skipped
  zone already reads at or below the target.
- **Fix in plan:** park D4, with a revival trigger: "a stand-down row whose recorder thermostat reading at the time was
  greater than effective_high + margin". The D0 check-mode probe already tests exactly that. If a trip-wire is still
  wanted, it must test the actual fault. One option is a stand-down with T unchanged while `hvac_action == cooling`
  for N hours. Without it, the ring side-key, two constants and four tests drop out.

### L1 — "The operator asked for a margin knob" is not backed by the card or the audit
- The card `HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1` (`kanban.data.yaml:34454-34474`) and the audit contain no margin ask.
- **Fix in plan:** cite the ask, or make the margin a rung-1 const at 0.0 (parsimony) and park the Number until a ask
  arrives. If it stays a Number, keep range 0-3 and step 0.5, but note Carrier reads whole degrees: 0.5 behaves like 0
  and 1.5 behaves like 1. Use step 1.0, or say so on the knob.

### L2 — A stale reading during a thermostat outage is treated as fresh
- `update_zone_climate_state` returns early on `unavailable` without clearing `current_temperature`
  (`hvac_zones.py:700-711`), so T is the last value seen, not None.
- Harm is nil, since a write to an unavailable entity buys nothing either. The plan should still say it, and the D1
  "None → fail open" verify should not claim that it covers outages.

### L3 — Daily counters should reuse `DailyCounter`
- `precool_standdowns_today` / `precool_writes_today` should use `DailyCounter` (`coordinator_diagnostics.py:880`;
  RESTART-SAFETY-DOCTRINE-1, already used for `_pre_arrival_triggers_today`, `sensor.py:14509`).
- Add the reuse to §1.1. Do not hand-roll a midnight reset.

### L4 — Adjacent waste outside scope: card it, don't build it
- The energy pre-cool (`hvac_predict.py:635`, reason `energy_precool`) has the same "never reads temperature" shape.
  INV-NOOP correctly leaves it untouched.
- Card it as the energy sibling, per the supersession audit's KEEP+WIRE bucket. It needs its own fire check, because
  banking below the current temperature is the point of energy pre-cool, so the stand-down semantics may differ.

## Claims verified (hold)
| Claim | Verdict | Evidence |
|---|---|---|
| Exactly two `_execute_zone_pre_cool` callers; only :698 is pre-arrival | HOLDS | grep: `hvac_predict.py:635`, `:698` (plus a comment at `number.py:3669`) |
| No other pre-arrival thermostat write | HOLDS, but see M1 | the S11 release is the only other write reachable from pre-arrival membership; it fires with no borrow only via M1. `_handle_person_arriving` (`hvac.py:7212-7281`) writes nothing; fans don't touch the thermostat; energy pre-cool is not arrival-triggered and is blocked by `is_borrow_active` when the other borrow is live |
| Season value reusable | HOLDS | `season = self._preset_manager.current_season` already at `:445`; months `hvac_const.py:1207-1208` (November = shoulder) |
| The `:764` gate idiom is reusable | HOLDS (idiom only) | it sits in `_should_energy_precool` (`:764-766`) and sets `_pre_cool_skip_reason`; the plan reuses the membership test, not the function. Fine |
| `zone.current_temperature` is the right reading | HOLDS | `hvac_zones.py:711` raw thermostat attr; this is the sensor the cool leg acts on. `avg_temperature` correctly rejected |
| Do not end on target reached | HOLDS | the borrow holds the leg at target; ending returns to the pre-borrow preset (Away 80 in the shoulder defaults, `hvac_const.py` SEASONAL_DEFAULTS) and lets the zone drift. The tick re-evaluation is real: the block runs every `_check_pre_conditioning`, gated only by `is_borrow_active` (`:697`) |
| Placement after the setpoint skip and before `begin_excursion` | HOLDS | `:1297-1300` then `:1305` begin; the latch/egress early-returns above it are unaffected |
| Shoulder floor oddity | HOLDS | shoulder default home cool 74 − 2 = 72, floored at 74 = Home cool; correctly a non-goal |
| Winter: the season gate is needed beyond the stand-down | HOLDS | winter Away cool 78 > effective 74, so the setpoint skip does not fire; a zone above 74 would be pre-cooled |
| Knob numbering / template | not re-derived; `PreArrivalWindowMinutesNumber` exists as the cited template |
| Fire-check numbers | plausible, not re-queried (no live DB access in this pass). They are internally consistent: 17/34 ≈ 50%, 45 borrows / 12 d ≈ 3.75/day (the plan says 2-4/day) |
| Acceptance criteria discriminate | MOSTLY | D1's avg-temperature and placement tests discriminate well. The D1 Live check is a sound oracle. D4 does not (M3) |
| Tier 2 | AGREED | removes writes, fails open, no shared-primitive edit, as long as M1 is fixed outside borrow code (S11 is predictor code, not the primitive) |

## Must-fix before build
1. M1: specify and test that the S11 release skips zones with no token (stand-down and off-season).
2. M2: change the episode key, and test it with repeat triggers.
3. M3: park D4 (or redesign it on a discriminating signal).

L1-L3 are cheap and belong in the same plan revision.
