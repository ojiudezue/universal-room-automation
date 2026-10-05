# URA v5.103.37 — No night EV ping-pong, poor nights hold the forecast floor, coordinators added one by one

Tier 3 (EC) + Tier 2 (coordinators, Phase A elevated to 3 reviews) + small fixes. Operator go 2026-10-03.

**Behaviour changes to expect:**
- EC-RUNG1-WAIT-EV-PINGPONG-1 — attain's "redirect solar" (rung_1) can no longer pause EVs at night — the solar estimate only counts daylight, and a latch carried from the day is released after dark. rung_0 stays sticky (hysteresis kept).
- On poor / very-poor forecast nights, the arbitrage WAIT stage holds the forecast drain floor (e.g. 30%). If the battery is already below it after the evening high-rate window, it parks at its current level — never below the configured reserve and never grid-charging (refill is attain's job). Evening high-rate discharge is unchanged (peak avoidance first).
- Side effect: on poor nights the EV battery-drain pause releases at the floor (~30%) instead of ~10%.
- CM-COORDINATORS-ADD-ONE-BY-ONE-1 — new installs start with only Presence; add other coordinators from the Coordinator Manager menu ("Add a coordinator" / "Remove a coordinator"). Existing installs keep exactly what runs today; an install whose master switch is off starts with nothing added. Each add/remove reloads the Coordinator Manager and the parent entry once.
- FAN-ORACLE-BOOT-FALLBACK-NOISE-1 — boot log: the 43-room "FanPolicyOracle fallback" burst at startup is gone (logged at DEBUG before the oracle attaches).

## EC daylight horizon + poor-night floor

**Status:** built on `feature/ec-daylight-poor-night`, not deployed. Tier 3 (4 framing-disjoint build
reviews + orchestrator re-verification + operator checkpoint before deploy; no restart while the house sleeps).
**Plan:** `docs/planning/PLANNING_ec_daylight_horizon_and_poor_night_floor.md` (plan reviews #1 and #2 binding).
**Cards:** EC-RUNG1-WAIT-EV-PINGPONG-1 (fix 1) + the poor-night WAIT-floor card (fix 2, mint at dispatch).

### What changed

### Fix 1 — no night-time EV pause/resume loop (rung 1)
- The rung ladder's charge-rate projection now counts the observed rate only while it is daylight
  (`sunrise <= now < sunset`, from `sun.sun`; fallback 07:00-19:00). Before sunrise and after sunset only the
  forecast solar term counts, so `arb_projection_rung1 == arb_projection_rung0` and rung 1 cannot start at night.
- 10-01 incident: SOC 8.9 %, EV 11.6 kW at 01:14 projected 100 % (EV load extrapolated over ~16 h of night).
  Now: 50.0 % for both projections, rung 2, EV left alone. Replay of the recorder night: 0 rung-1 ticks
  before sunrise (pre-fix code on the same inputs: 11 in 01:14-03:20).
- Daylight projections are unchanged (byte-identical; replayed against the recorder and an independent oracle).
- `EnergyProjector.project_soc_at_boundary` gained an optional `sunrise_dt` (default `None` = unchanged for every
  other caller).

### Fix 2 — poor nights hold the drain floor (operator ruling 2026-10-03)
- On poor/very_poor target days with arbitrage on, WAIT parks at the drain floor (`current_offpeak_drain_target`,
  30 % with the live sliders) while SOC is above it, and at `max(reserve_soc, SOC)` once SOC is at or below it.
  Before: WAIT parked at `reserve_soc` (10 %), so the poor/very_poor sliders did nothing while the gate was open.
- **Park only.** WAIT never grid-charges toward the floor. Any refill decision belongs to attain.
- Never lower than the old behaviour (new WAIT reserve >= old on every input). With SOC below `reserve_soc`
  (09-30 night, SOC 7-9 %) WAIT still emits 10, not 7-9.
- This deliberately reverses the v4.5.0 "Mistake #7" note (no artificial drain target in WAIT).

### Behaviour changes to know about
- **EV drain-release floor rises on poor nights** (plan review #1 R1-1). The commanded WAIT floor becomes the
  EV drain rule's release floor, so `effective_release_floor` is ~30 on a poor night (was 10). The EV runs on
  grid, not battery, while the battery is parked.
- **Abort-path WAIT holds the floor too** (review #2 F9): after a charge-window recheck abort the battery parks at
  the floor for the rest of the chunk instead of draining to `reserve_soc`.
- Status text: the WAIT reason reads "Arbitrage WAIT — holding drain floor N%"; `next_action_estimate` reads
  "waiting for charge window, holding N% floor (lead_time=…)" or "arbitrage chunk completed — holding N% floor".
- `current_park_floor` / `effective_release_floor` / `current_offpeak_drain_target` now agree with what is
  commanded on WAIT ticks (they showed 30 while 10 was commanded).
- The ledger behind `current_park_floor` moves in 1 % steps under the 2 % write deadband while SOC is below the
  floor, so it can lag by up to 1 point (review #1 R1-2).
- **Residual (not fixed, documented):** rung 1 can still enter just after sunrise if an EV session is still
  drawing (review #2 F6). Detector: the SPEC INV-1 trip-wire card (>2 strategy-caused EV toggles/h → NM).

### Kill switch
Set `number.ura_energy_coordinator_off_peak_drain_poor` and `_very_poor` equal to `reserve_soc`: WAIT then parks
exactly as before. Fix 1 has no knob (it only removes a night-time extrapolation).

### Live validation (prospective — replace with a `Validated <date>` table after restart)
- First poor post-midnight night with EV draw: `arbitrage_rung` stays `rung_2`, `arb_projection_rung1` ==
  `arb_projection_rung0` before sunrise, zero `evse_paused_by_arbitrage` entries between sunset and sunrise,
  EV turn-ons ≤ 2/h.
- Next poor-target night: `arbitrage_phase=wait`, `current_commanded_reserve` == `current_offpeak_drain_target`
  (30) while SOC > 30, `hold_owner=arbitrage_wait`, `park_floor_source=commanded`; morning CHARGE still fires at
  lead time and reaches the peak buffer by the boundary.
- Discriminator: commanded 30 but SOC still falls to 10 ⇒ the hardware write is not landing (check
  `command_trail`), not a strategy failure.

## Coordinators added one by one

Plan: `docs/planning/PLANNING_cm_coordinators_add_one_by_one.md`. Phase C (hide devices/entities
of coordinators that are not added) is NOT in this build.

### What changes

- **Enabled switches tell the truth.** Every coordinator has one default in
  `COORDINATOR_ENABLED_DEFAULTS` (`const.py`). The 8 registration gates in `__init__.py`, the
  Enabled switch, NM `enabled` and the music-following kill switch all go through
  `coordinator_gate.coordinator_should_run`. Before: on a fresh install the Energy, HVAC and
  Notifications switches read ON while those coordinators were not running.
- **New installs start with only Presence added** (and running). Everything else is added from the
  Coordinator Manager.
- **Existing installs: nothing starts or stops.** A one-shot migration (runs at integration setup,
  even with the Domain Coordinators switch off) writes each coordinator's current run state
  explicitly and marks the running ones as added. Sentinel: `coordinators_added_migration_done`
  on the CM entry.
- **Existing installs with the Domain Coordinators switch OFF:** nothing is marked added and every
  coordinator's run key is written off (nothing was running, so nothing changes). The operator then
  adds coordinators one by one; the first add turns the master switch on and starts only that
  coordinator (plus Presence for Climate/Security). Writing the keys off, not leaving them unset,
  is what stops the five default-on coordinators from all starting on that first add — the run
  gate (`coordinator_should_run`) reads only the run key.
- **Coordinator Manager > Configure** now shows:
  - **Add a coordinator** — lists coordinators not yet added. Picking one opens its settings
    (Safety, Security, Energy, Climate (HVAC) tuning, Notifications) or a one-screen confirm
    (Presence, Music following, Appliances). It is added only when you save. Closing the dialog
    adds nothing. Adding Climate or Security also adds Presence.
  - Settings for **added** coordinators only.
  - **Remove a coordinator** — stops it. Its settings are kept; adding it again restores them.
  - Signal responses and Optimizer, as before.
- **First add turns on Domain Coordinators** if it was off (that is the one parent reload). With
  it already on, add/remove schedules one parent reload, same as the Enabled switch.
- **Reload cost:** each add or remove reloads the Coordinator Manager entry AND the parent
  integration entry (the CM options save reloads the CM; the run-set change reloads the parent so
  the registration gates re-run). Expect a short coordinator blink per add/remove.
- **Upgrade boot does not reload the CM:** the migration seeds the CM listener's last-applied
  snapshot before writing, so the update listener sees no change.
- A coordinator that is not added shows its Enabled switch as unavailable (attribute
  `added: false`); turning it on does nothing until it is added.
- The integration "Add coordinator" entry now says to use Coordinator Manager > Configure > Add a
  coordinator.
- **Entitlement hook** (`entitlements.can_use_coordinator`): allows everything today. Called from
  the Add step (deny = abort with the reason) and from the run gate (deny = not run, logged once,
  repair issue `coordinator_not_entitled_<id>`, text uses the plain coordinator name; cleared
  again when the coordinator is allowed).

### Live acceptance (to fill after deploy)

| Check | Expected | Result |
|---|---|---|
| Main house: registered coordinator set before vs after | identical | |
| Main house CM options | `coordinators_added` = running set; sentinel true | |
| Second home: Energy/HVAC/NM Enabled switches | `off` with no operator action (if their keys were never written) | |
| Second home: add Security from the CM menu | Security Enabled `on`, security sensors available | |
| CM menu on second home | HVAC settings not listed until added | |

### Not done

- Phase C (defer entity/device creation) — held, Tier 3, evidence trigger in the plan.
- `AUDIT_onboarding_first_run_path.md` step 8 / Stage D row correction — that file is not on this
  branch (untracked in the main checkout); correct it there.
- Full registration-block run (real `async_setup_entry`) is not exercised in tests. The run set is
  computed by the pure helper `coordinator_gate.coordinators_to_register` (behaviour-tested under
  defaults and entitlement deny); a source check pins that each of the 8 sites tests membership.
- Removed the unreachable legacy `coordinator_toggles` options step (no menu routed to it).

## Live validation
### Validated 2026-10-03 (checked ~20:20 CDT on v5.103.38)

| Check | Result | Evidence |
|---|---|---|
| 8 coordinators registered, Enabled switches truthful | PASS | all on, `added: true` |
| `coordinators_added` = all 8; migration flag set | PASS | CM options in core.config_entries |
| No CM reload storm at boot | PASS | system log clean |
| FAN-ORACLE-BOOT-FALLBACK-NOISE-1 | PASS | 0 `FanPolicyOracle` warnings |
| peak_buffer_target 90 / lead 150 (operator knob turns) | PASS | battery strategy attrs |
| drain_targets_effective, current_offpeak_drain_target = 30 (target day poor) | PASS | attrs |
| No rung_1 after sunset (19:10-20:17) | PASS | `arbitrage_rung` null; still in discharge phase |
| No EV paused by arbitrage after sunset | PASS | `evse_paused_by_arbitrage: []` throughout |
| WAIT holds forecast floor overnight | PENDING overnight | query: battery_strategy rows with arbitrage_phase='wait' — commanded reserve must equal 30 while SOC>30, else max(10,int(soc)), never grid charge |
| No EV toggles >2/h overnight | PENDING overnight | count garage EV switch changes 00:10-12:00 2026-10-04 |
