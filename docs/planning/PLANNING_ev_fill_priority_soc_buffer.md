# PLANNING — EV fill-priority SOC re-pause band (EV-FILL-PRIORITY-SOC-CHATTER-1)

- Card: `EV-FILL-PRIORITY-SOC-CHATTER-1` (`docs/planning/kanban.data.yaml:126-161`)
- Thread: energy
- Tier: **Tier 2-DB** — changes an EV pause owner (`fill_priority`), interacts with
  drain / arbitrage / load_shed / breaker / excess-solar precedence. Three framing-disjoint
  reviews before ship. Not Tier 3 (no state machine, no cost-and-safety simultaneously; the
  grid-charge breaker clamp is upstream of this change).
- Operator decision 2026-10-15b: **APPROVED option A** — resume at 80%, re-pause only
  below 77%. Buffer applies ONLY after a resume. First pause below 80% is unchanged.
- Prior approval 2026-10-15 ("see if config fixes these first") already discharged:
  the only existing knob (`CONF_ENERGY_FILL_PRIORITY_SOC`,
  `energy_const.py:1077-1079`) is a single threshold used symmetrically for pause and
  resume — moving it only moves the chatter point. Config does NOT fix this.
- Not to be confused with `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1` — different owner
  (`arbitrage`), different mechanism (rung-1 ↔ WAIT load-feedback loop at night).
  Observed 10-11 19:26:45Z garage_a toggles were `pause_owners=fill_priority`,
  `strategy=self_consumption`, SOC 79-81% — this card's mechanism.

## 1. Institutional context verified

### Code surveyed end-to-end
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py:1065-1094`
  — fill-priority defaults + conf key, drain/plug grace, surplus-pct knob.
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py:1337-1504`
  — SOC-ladder validator; fill-priority invariant #4 `fill_priority_soc <=
  excess_solar_soc` at `:1446-1456` + canonical doc at `:1488, :1501`.
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py`
  (EV path — `EVPool`):
  - `:585` init `_paused_by_fill_priority: set[str] = set()` — **RAM-only**, no
    persistence, no RestoreEntity hook. Boot = empty set.
  - `:589` `_fill_priority_solar_ok`, `:600` `_fill_priority_would_hold` —
    cross-tick publications.
  - `:2668-2921` `determine_fill_priority_actions` (the subject of this card).
    - `:2770` pause: `soc < soc_threshold and forecast_healthy and is_on`.
    - `:2773` `resume_soc_met = soc >= soc_threshold` — the symmetric edge.
    - `:2844-2864` pause action + membership add + dispatch claim.
    - `:2865-2919` resume branch: `resume_soc_met or forecast_decayed` →
      membership discard + funnel release.
  - `:2239-2245, :2596-2602, :3135, :3452, :3547, :3882, :3987` — other pause owners
    that CONSULT `_paused_by_fill_priority` as a precedence gate (do not touch its band).
  - `:3225-3278` sensor surface: `paused_by_fill_priority`, `pause_reason_human`,
    `fill_priority_target_soc`, `fill_priority_solar_ok`, `pause_dispatch_state`.
  - `:3491-3547` `release_all_fill_priority` (excess-solar toggle OFF).
- `energy_pool.py:4384-4540+` — PLUG mirror `determine_fill_priority_actions` on
  `PlugPool`. Mirror MUST change in lockstep with the EV path per existing parity
  comments (`:4407, :4442-4445, :4504, :4515-4540`).

### Grep-verified existing hysteresis / band patterns
- Forecast-side band already exists: `forecast_healthy >= X` vs
  `forecast_decayed <= X - safety_margin` (`energy_pool.py:2719-2731`, mirror
  `:4414-4424`). The ingredient is `DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH =
  1.0 kWh` in `energy_const.py:1078`. The SOC-side has NO such band today —
  that is the defect.
- `EV_PAUSE_DISPATCH_GRACE_SECONDS = 30.0` (`energy_const.py:1072`) — unrelated
  (anti-cache-flicker on manual-override detection), not a repause suppressor.
- `EV_BATTERY_DRAIN_COOLDOWN_SECONDS = 3600` (`energy_const.py:1066`) — a TIMER
  on a different owner; explicitly rejected on this card (parked alt: "timer is
  the time-coupled ingredient that review history flags as risky").
- `EVSE-SOLAR-STOP-CONDITIONS-1` carries a related SOC-band idea for
  excess-solar sessions (resume_ev 95 / fill 80) — different owner, out of scope.

### Prior-art scan verdict (REUSE vs NEW)
- `DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT` — **NEW**. Grep of
  `energy_const.py` for `*HYSTERESIS*|*REPAUSE*|*BAND*` returns no SOC-side band
  constant on any pause owner. Closest adjacent (`DEFAULT_FILL_PRIORITY_SAFETY_MARGIN_KWH`)
  is forecast-side, kWh, not SOC. Operator-approved value 3 (pct).
- Pause/release machinery — **REUSE**: `_paused_by_fill_priority`,
  `_claim_pause_dispatch_owner`, `_release_pause_dispatch_owner`,
  `_charge_on_or_defer`, cross-owner precedence gate. No new state introduced.
- Sensor surface — **REUSE**: existing `paused_by_fill_priority` set is the
  observable discriminator for the invariant (see §6).

### Prior planning docs / memos
- `docs/planning/kanban.data.yaml:126-161` — this card (full).
- Related cards: `EC-EV-TOGGLE-TRIPWIRE-1` (shipped v5.103.49, the alarm that caught
  this), `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1` (different mechanism — DO NOT merge
  logic; the two cards cover disjoint pause owners), `EV-ARBITRAGE-RELEASE-IGNORES-FILL-PRIORITY-1`
  (shipped — unrelated interaction direction).
- `docs/planning/DESIGN_ec_degraded_data_policy.md` §9.1 / §9.3 — context for the
  sibling arbitrage flap, confirms this is a distinct owner.
- Adjacency sweep `adjacency_2026_10_12` on the card confirms NEW (no fill-priority
  hysteresis deliverable in BACKLOG or any planning doc).
- Memory: [[feedback_tier2db_for_regression_prone]] — Tier 2-DB protocol default for
  changes affecting a shared primitive (pause-owner set) across coordinators.

### Config-first discharge
Checked: `CONF_ENERGY_FILL_PRIORITY_SOC` is the only operator-facing knob; it is a
single number used for BOTH the pause edge (`soc < soc_threshold`,
`energy_pool.py:2770`) and the resume edge (`soc >= soc_threshold`, `:2773`). No
existing option-flow field, number entity, or module constant encodes a band. A
code change is required.

## 2. The problem (measured)

With `fill_priority_soc = 80`:
- Pause when `SOC < 80` and solar healthy → EV turns off.
- SOC climbs on battery charge to 80 → `resume_soc_met` true → EV resumes.
- 11.6-11.7 kW EV draw drops SOC to 79 within one tick → re-pause.
- Loop at ~5-minute cadence.

Evidence (on card): 10-11 19:26:45Z garage_a 3 toggles in an hour; same pattern on
10-09; 2 of 7 logged days. Mechanism confirmed by `pause_owners=fill_priority`,
`strategy=self_consumption`, SOC 79-81% range.

## 3. Falsifiable invariant

> **INV-1:** With `grid_charge_on=False`, `force_charge_active=False`,
> `fill_priority_inert=False`, `forecast_healthy=True`, and SOC held in the
> half-open band `[soc_threshold - repause_band_pct, soc_threshold)` after a
> prior fill-priority resume, no EV or plug SHALL transition
> `_paused_by_fill_priority` membership in either direction on any tick.
>
> **INV-2 (counter-invariant to defend):** The FIRST pause below `soc_threshold`
> (when the EVSE is NOT currently in `_paused_by_fill_priority`) remains
> UNCHANGED — the band applies ONLY on the re-pause-after-resume path.
>
> **INV-3 (floor):** With SOC `< soc_threshold - repause_band_pct` and solar
> healthy, a pause SHALL fire on the next tick regardless of prior-resume
> history. The band is a hysteresis, not a hold-off.

Observations that would FALSIFY INV-1 (what the oracle looks for):
- A `fill_priority_release` row in `ura_activity_log` followed by a
  `fill_priority_pause` row for the same `switch` entity within one tick while
  SOC was recorded in `[77, 80)`.
- `paused_by_fill_priority` attribute on the EV status sensor flipping
  present→absent→present within the same SOC band inside 10 minutes.

Observation that discriminates INV-1 from INV-2 (per QUALITY_CONTEXT consumer
rule): a FIRST-time pause at SOC=78 (never previously paused this session) MUST
still fire — if it does not, the fix regressed INV-2.

## 4. Knob ladder

Per operator policy "Numbers Get Knobs" and the card's `knobs:` field:

| Knob | Name | Default | Rung | Why this rung |
|---|---|---|---|---|
| Re-pause SOC band (pct) | `DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT` | **3** | **Rung 1 (module constant)** | Stability margin, not a per-deployment policy knob. Operator-approved value. `0` MUST disable the band (legacy behaviour) and is the kill-switch. Change requires code review — matches drain-cooldown precedent. |

- NOT options-flow (not per-deployment).
- NOT a Number entity (not legitimately tuned by observation; operator decision
  on the card: "a stability margin the operator should not need to tune").
- Kill-switch semantics documented on the constant: `0` = today's behaviour.

Related constant surveyed but UNCHANGED: `CONF_ENERGY_FILL_PRIORITY_SOC` keeps
its current single-number operator-facing contract.

## 5. Design (do not build — spec only)

### 5.1 Add module constant

`energy_const.py` after `:1078`:

```
# EV-FILL-PRIORITY-SOC-CHATTER-1: resume → re-pause SOC hysteresis.
# After a fill-priority RESUME, suppress re-pause until SOC falls below
# (fill_priority_soc - DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT). The
# FIRST pause below fill_priority_soc (no prior membership) is unchanged.
# 0 disables (legacy single-threshold behaviour).
DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT: Final = 3
```

### 5.2 Pause-site change (EV path — `determine_fill_priority_actions`)

Current (`energy_pool.py:2768-2772`):
```
pause_conditions_global = (
    soc is not None
    and soc < soc_threshold
    and forecast_healthy
)
```

Spec: split the pause gate into FIRST-pause vs RE-pause.

- First pause (EVSE NOT in `_paused_by_fill_priority`): keep today's edge
  `soc < soc_threshold`.
- Re-pause (EVSE WAS in `_paused_by_fill_priority` on a prior tick, got released,
  and is `is_on`): require `soc < (soc_threshold - repause_band_pct)`.

The resume edge at `:2773` (`resume_soc_met = soc >= soc_threshold`) is
UNCHANGED — resume still fires at 80, matching the operator spec "resume at 80".

**Membership-based discrimination is wrong.** On a legitimate resume (`:2916`
discards the EVSE), the next-tick membership is False — so "already in the set"
cannot discriminate "fresh entry" from "post-resume re-entry". A dedicated
`_recently_released_by_fill_priority: dict[str, float]` latch is required, keyed
on EVSE id → monotonic timestamp set at the resume site (`:2916`) and cleared
when SOC drops below the band floor OR when another owner takes over. The
re-pause gate reads the latch, not the active-pause set.

Equivalent plug-path change at `energy_pool.py:4448-4451` + `:4515-4540`
(PlugPool mirror). Same latch, same gate split.

### 5.3 Latch lifecycle (consumers + producers)

- **Producer:** resume branch at `:2916` (EV) and `:4540+` (plug) — on terminal
  resume, record `_recently_released_by_fill_priority[id] = _time.monotonic()`.
- **Consumers:**
  - Re-pause gate in the same function (the one new consumer).
  - Clear on `release_all_fill_priority` (`:3491-3547`) — explicit toggle OFF
    must reset the latch so the next legitimate re-entry below 80 is immediate.
  - Clear on `force_charge_active` branch (`:2785-2793`, `:4457-4466`) — same
    reason.
  - Clear on cross-owner precedence steal (`:2871-2888`) — if drain / arbitrage
    / grid_cap / load_shed / blind_window takes over, FP's re-entry logic must
    reset so the next time FP is unopposed and SOC is below the floor, it
    pauses immediately.
  - Clear when SOC drops below `soc_threshold - repause_band_pct` — latch is
    satisfied, next pause fires normally.
- **Pause-dispatch owners that READ `_paused_by_fill_priority`** (lines
  `:2245, :2602, :3135, :3452, :3547, :3882, :3987`): unaffected. The new latch
  is additional, not a replacement.

### 5.4 Restart / reload behaviour

- `_paused_by_fill_priority` is RAM-only today (`:585` empty-set init). Boot
  with SOC in `[77, 80)`:
  - Today: EVSE is NOT in the set → first-pause path → pause fires at
    SOC=78. (Unchanged under this spec — INV-2.)
  - Under this spec: identical. The latch is also RAM-only — a reload erases
    "we previously released here" and the first tick after boot is treated as
    a first pause. **This is correct**: a reload loses the oscillation history,
    and one pause at SOC=78 after reload is not chatter.
- No persistence requirement. Document the lossy-reload semantics in the
  constant's docstring.

### 5.5 Validator / ladder invariant #4

`energy_const.py:1446-1456` (`fill_priority_soc <= excess_solar_soc`) is
unaffected — the band is a module constant below `fill_priority_soc`, not an
operator knob. The validator does not need a new check. (Open question Q1
below asks whether to add one anyway for safety.)

## 6. Acceptance criteria

| ID | Criterion | Verify (static / test / live) |
|---|---|---|
| A1 | INV-1 holds in-suite under forecast_healthy, no competing owners, SOC walked 80→79→80→79 over four ticks | Test: pause/release counts stay flat after first resume |
| A2 | INV-2 holds: fresh EVSE at SOC=78 pauses on tick 1 | Test: first-pause path unaffected |
| A3 | INV-3 holds: EVSE post-resume at SOC=76 pauses on tick 1 | Test: band floor fires |
| A4 | Band=0 reproduces legacy chatter (regression anchor) | Test: `DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT=0` monkeypatch → 4 toggles over 4 ticks |
| A5 | Band=100 (band > threshold) does NOT prevent the first pause | Test: SOC=50 fresh EVSE still pauses |
| A6 | Plug mirror parity | Test: both EV and plug paths show matching ledger shape |
| A7 | Force-charge clears the latch | Test: force-charge during resume-latch → next SOC=79 tick pauses immediately once force-charge clears below floor |
| A8 | Cross-owner steal clears the latch | Test: drain takes over during latch → latch clears → fresh FP pause fires at SOC=78 after drain releases |
| A9 | `fill_priority_inert` (peak / off_peak-at-night / mid_peak-post-peak) still releases cleanly | Test: existing inert tests unchanged |
| A10 | Forecast unhealthy during latch does NOT turn pause into "stuck released" | Test: `forecast_decayed` during latch → no spurious pause; `forecast_healthy` returns + SOC in band → still no pause |
| L1 | **Live:** on the first charging day after deploy, with `fill_priority_soc=80` and `band=3`, `ura_activity_log` shows ZERO `fill_priority_pause` rows for a garage charger within 10 minutes of a prior `fill_priority_release` row for the same `switch` while SOC remains in `[77, 80)` | Query `ura_activity_log` + `anomaly_log` (ev_toggle_tripwire count) over 24h |
| L2 | **Live:** a legitimate first pause fires when the operator starts a charge below 80 (observe once) | `ura_activity_log` + sensor surface `paused_by_fill_priority` populates |
| L3 | **Live:** `anomaly_log.ev_toggle_tripwire` rows for the first full charging day = 0 | Same query as `EC-EV-TOGGLE-TRIPWIRE-1` disposition |

## 7. Config-extreme tests (per Tier 3-style stringency, lifted into Tier 2-DB)

- **Band = 0** → legacy chatter reproduces (A4). Kill-switch validation.
- **Band = 100** → first pause still fires (A5). Degenerate but legal.
- **Band = `fill_priority_soc`** (e.g. 80) → latch floor at 0; re-pause only
  on empty battery. Validator / consumer sanity.
- **Band > `fill_priority_soc`** (e.g. 90 with threshold 80) → floor goes
  negative. Clamp to 0 at consumption; test it.
- **Threshold edges:** `fill_priority_soc = 80`, SOC exactly 77 (floor edge) —
  pause fires; SOC exactly 80 (ceiling) — resume fires (unchanged).
- **Forecast unhealthy during latch** → see A10.
- **Grid-charge ON during resume** → plug path M1 holds the resume
  (`:4529-4535`); verify the latch is NOT set in that case (no resume
  happened).

## 8. Producer / Consumer map (per Producer AND Consumer rule)

### `_paused_by_fill_priority` (existing)
- **Producers** (writers): `energy_pool.py:2787, :2819, :2851, :2880, :2916,
  :3156, :3496, :3525, :4444, :4460, :4486, :4501, :4523, (plug mirror
  terminal-resume)`.
- **Consumers** (readers): `energy_pool.py:2245, :2602, :3135, :3268, :3413,
  :3452, :3547, :3882, :3987` — precedence gates in drain / arbitrage /
  load_shed / blind_window / cooldown and the sensor-surface serializer.
- **Dependency health:** SOC source — `BatteryStrategy.soc` via Envoy LKG
  fallback (shipped v5.103.39, `EC-DEGRADED-DATA-POLICY-1`). Forecast health —
  `remaining_forecast_kwh` from `WeatherProviderManager`. Both healthy today
  per the 2026-10-07 LKG write-back validation.

### `_recently_released_by_fill_priority` (NEW)
- **Producer:** terminal resume branch in `determine_fill_priority_actions`
  (EV + plug) only. No other owner may write it.
- **Consumer:** the re-pause gate in the SAME function only. No cross-
  coordinator read. Scoped to the fill-priority state machine.
- **Trust tier:** behavioural (controls dispatch); not a display value.

## 9. Non-goals

- Minimum-hold timer on the pause (parked on the card: "a timer is the
  time-coupled ingredient that review history flags as risky").
- Changing `fill_priority_soc` default (80 stays).
- Changing the resume condition (`soc >= soc_threshold`) — resume still at 80.
- Touching the arbitrage-WAIT loop (`EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1`,
  different owner).
- Validator / ladder invariant #4 edit (unless Q1 says otherwise).
- `EVSE-SOLAR-STOP-CONDITIONS-1` excess-solar session band (different owner).
- Persistence of either `_paused_by_fill_priority` or the new latch across
  reload (see §5.4).

## 10. Open questions for operator / builder

1. **Validator new rule?** Should `energy_const.py` grow a cross-field check
   `DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT < fill_priority_soc`? Band
   is a module constant today (no operator knob), so a static assertion at
   import time may be simpler than a runtime validator entry. **Recommend:**
   assertion at import, no validator entry. Confirm.
2. **Latch TTL?** Should the latch auto-expire after N seconds absent any
   clearing condition, as a safety net against a stuck latch pinning the EVSE
   released forever? The listed clear conditions in §5.3 should cover every
   legitimate exit, but a 1-hour TTL (parity with `EV_BATTERY_DRAIN_COOLDOWN_SECONDS`)
   is cheap insurance. **Recommend:** add a 1-hour TTL as belt-and-suspenders;
   it is a safety timer on a non-timer policy, not a hold-off. Confirm.
3. **Sensor surface:** expose `fill_priority_repause_band_pct` + a boolean
   `fill_priority_in_repause_latch` on the EV status sensor for the operator
   to observe? **Recommend:** yes, both — read-only, same block as the other
   fill-priority surfaces at `:3268-3278`. Confirm.
4. **README anchor:** this will ship as a numbered deliverable in the next
   patch (`5.90.x` cadence). Operator pick: standalone cycle or ride with
   the next EC batch?

## 11. Tier-2-DB review framings (for the plan-reviewer and the three post-build reviewers)

- **A — local correctness + edge cases:** band arithmetic, clamp to 0, latch
  set/clear sites, first-pause vs re-pause discrimination (NOT via membership).
- **B — cross-coordinator / pause-owner integrity:** drain, arbitrage,
  grid_cap, load_shed, blind_window, force-charge, excess-solar all still
  consult `_paused_by_fill_priority` identically; new latch leaks nothing;
  INV-2 (first pause) and INV-3 (floor) hold on byte-identical no-op paths.
- **C — test authority + plug-mirror parity + restart:** mutation drill per
  site (comment out the latch at each clear site, confirm a SPECIFIC test fails);
  plug mirror diffed line-for-line; reload-wipes-latch is tested and documented.

## 12. Report (per operator request)

- **Path:** `/Users/okosisi/Code/universal-room-automation/docs/planning/PLANNING_ev_fill_priority_soc_buffer.md`
- **Tier:** Tier 2-DB (3 framing-disjoint reviews; config-extremes; live
  acceptance).
- **Invariant (falsifiable, headline):** with SOC held in `[77, 80)` after a
  prior fill-priority resume and no competing owner / inert condition, no EV
  or plug transitions `_paused_by_fill_priority` membership in either
  direction. First pause below 80 (no prior membership) and re-pause below
  77 both still fire.
- **Knob:** `DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT` = 3, rung 1
  (module constant, `0` = kill switch / legacy).
- **Open questions:** 4 — validator rule, latch TTL, sensor surface, ride-
  along cycle choice.

## Orchestrator rulings on open questions (2026-10-15)
- **Q1:** the band is a rung-1 module constant, so a unit test asserting `0 <= DEFAULT_FILL_PRIORITY_REPAUSE_HYSTERESIS_PCT < DEFAULT_FILL_PRIORITY_SOC` suffices. The runtime guard clamps to the effective band = min(band, soc_threshold) so an operator setting fill_priority_soc very low cannot invert it. No validator entry.
- **Q2:** no TTL. The latch already has a discharge (SOC below floor, force charge, cross-owner steal, release_all). A timer would add a time-coupled ingredient for no measured benefit.
- **Q3:** no new sensor. If an existing EC diagnostics attribute dict already lists fill-priority pause state, add the latch there (one key); otherwise skip.
- **Q4:** standalone cycle (operator approved now).
