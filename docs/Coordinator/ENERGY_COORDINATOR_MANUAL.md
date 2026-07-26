# Energy Coordinator — Operator Manual

**Audience:** the homeowner running URA.
**Scope:** what the Energy Coordinator (EC) does day to day, the knobs
you can turn (and where they live), the surfaces you can watch, and how
to intervene safely.
**Current through:** URA v5.18.0 (deploying 2026-07-16).

This is NOT a code walkthrough. For architecture, see
`ENERGY_COORDINATOR_DESIGN_v2.3.md` (historical design spec).

---

## 1. What the EC actually does

The EC is the whole-house energy brain. It decides, minute by minute:

1. **What the Enphase battery should do** — how much of its capacity to
   reserve, whether to allow the grid to charge it, whether to allow
   grid export, and which storage mode (`self_consumption` /
   `savings` / `backup`) to sit in.
2. **When to charge the EVs** — pause during peak/mid-peak when
   arbitrage says so, resume off-peak, divert excess solar to the L2
   EVSEs before it exports.
3. **When to run the pool** — reduce VSF pump speed during expensive
   hours; restore off-peak.
4. **How to inform the HVAC Coordinator** — via constraints (pre-cool,
   coast, shed) rather than direct thermostat writes.

Everything downstream of the EC is either an **actuator write** (with
verification — see §5) or a **published constraint** the HVAC
Coordinator honors.

---

## 2. How it decides (in plain language)

### 2.1 The TOU-driven rhythm of the day

PEC has three periods (summer, illustrative): OFF_PEAK cheap /
MID_PEAK moderate / PEAK expensive (4–8pm). The EC's default posture:

- **Off-peak:** allow drain to a *drain target* set by tomorrow's solar
  forecast (see §2.2). If arbitrage says today is worth grid-charging
  the battery, do so in the pre-peak window.
- **Mid-peak (summer):** freeze battery at whatever SOC it's at when
  the boundary hits — this locks in solar gains earned during off-peak
  so they survive to peak. (Confirmed operator understanding 2026-07-16.)
- **Peak:** discharge the battery to cover home load (and if solar
  covers home, export battery credits to the grid — export is priced at
  the same $/kWh as import, so peak export is the highest-value use).

### 2.2 Solar day classification (drives everything else)

Every morning the EC classifies today's expected solar production into
one of `excellent / good / moderate / poor / very_poor`, using
**monthly P25/P50/P75 thresholds** (`SOLAR_MONTHLY_THRESHOLDS`,
`energy_const.py:81`) — not one fixed threshold year-round. This class
drives:

- The **drain target** (how low to allow battery to fall off-peak — if
  solar will refill tomorrow, drain deeper; if not, protect reserve).
- The **arbitrage gate** (grid-charge to peak buffer only makes sense
  on `poor / very_poor` days when solar won't refill on its own).

You see today's class in `sensor.ura_energy_coordinator_battery_strategy`
as the `target_day_class` attribute.

**Important nuance (operator-validated 2026-07-16):** the *reserve* is a
discharge FLOOR, not a charge CEILING. Setting reserve = 60% doesn't
make the battery target 60%; it means "don't discharge below 60%". The
battery still charges toward 100% from solar.

### 2.3 Arbitrage (grid-charge into peak, then hold)

On days where forecast says peak-hour need > solar refill, the EC will:

1. **Grid-charge** the battery in an off-peak/mid-peak window sized by
   `arbitrage_charge_lead_time_min` (see §3), aiming at the
   `peak_buffer_target`.
2. **Once a grid-charge chunk completes**, reserve **locks at that
   target until the TOU boundary** — this is the "completed-chunk HOLD"
   contract shipped in v5.17.1 (Tier-3, invariant I-AH1). The lock is
   what stops a "we bought expensive electrons then leaked them" leak.
3. **At the TOU boundary**, an at-boundary tick (v5.17.3, +5s past the
   boundary) re-evaluates and releases the lock as the peak begins.

### 2.4 EV charging

- **Off-peak:** ensure-on (v4.7.28); paused EVs resume automatically.
- **Peak / mid-peak arbitrage windows:** paused (URA tracks who it
  paused, so it only un-pauses its own pauses; won't clobber a manual
  start).
- **v5.15.0 charge-start dead-band fix:** when the drain-pause is
  released the EC now reads the emitter's *live commanded floor*,
  off_peak-gated, so an EV parked at (say) 40% doesn't get vetoed
  overnight against a static 10% floor. L1 and L2 EVSEs are on parity.
- **Excess-solar diversion:** when battery SOC ≥ **`excess_solar_soc`**
  (default 95%; number entity — see §3), surplus solar routes to the L2
  EVSEs before it exports. Verified firing 2026-07-16 14:00.

### 2.4a Battery-Aware EV Charging (v5.20.0/v5.21.0, ACTIVATED 2026-07-17)

The hold-then-eval night transition. When a car is plugged in at off-peak
with the home battery still high, the EC no longer just holds the battery
for the car — it *decides*:

1. **Hold** (state `hold_only`): battery holds; after the **Decision
   delay** (default 10 min) it evaluates.
2. **Evaluate**: does "let the battery drain to its target, THEN charge
   the car" fit before **Latest charge start** (default 03:00), given
   the overnight house load estimate, charger rate (L1 auto-holds — a
   16 h charge never fits), and **Typical charge needed** per plugged
   car? A **Charging time buffer** (default 60 min) pads the estimate.
3. **Transition** (`transitioned`): pause the EVSE(s) (owner `dp`), pin
   the composed reserve floor at the drain target (max()-composition —
   can only raise), let the battery serve the house.
4. **Release**: at floor (sticky, peer/TOU-aware — a deferred release
   keeps the claim and retries) or unconditionally at Latest charge
   start (liveness INV-DP2). Kill-switch OFF mid-flight reverts cleanly.
   Restart mid-transition drops to `hold_only` and orphan-cleans.

**Shadow mode:** while the switch is OFF, the eval still runs and
publishes `shadow_decision` / `shadow_reason` / `shadow_last_eval_snapshot`
on the EV Charging Plan sensor — what it *would* have done, zero
actuation (mutation-enforced invariant). Use this to build confidence
before enabling; it's how the feature earned activation on 2026-07-17.

### 2.4b EVSE precedence — who can start/stop a charger, in enforced order

Ratified 2026-07-20 by the tri-mechanism reconciliation audit
(excess-solar x TOU x BAEC) run before the DP-yield ship. This is the
code-enforced order, not aspiration; sites cited from that audit.
Unified objective each row serves: **grid** = avoid expensive grid
energy, **solar** = use excess solar, **battery** = don't
unnecessarily drain house storage.

| # | Owner / claim | Serves | Where enforced |
|---|---|---|---|
| 1 | Manual URA kill-switch re-pause (`_paused_by_us`, peak/mid-peak) | grid | energy_pool.py ~:540-568 |
| 2 | Force-Charge admin override (`_force_charge_until`) | operator escape | energy_pool.py ~:551-556, :703-724 |
| 2.5 | Blind-window guard (`_paused_by_blind_window`) — pauses/defers while `blind_hold_active AND NOT reserve_write_verifiable()` (raw entry predicate). Debounced by `CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S` so sub-2-min Envoy blips do not flap. Two sanctioned INV-BW1 escapes: (a) row 2 force-charge (B3 drains membership BEFORE the 2a peer-guard so ensure-on reaches dispatch); (b) TWO liveness paths — max-defer expiry (past `CONF_BLIND_WINDOW_MAX_DEFER_MIN`) AND DP must-start-by fire — both route through `EnergyCoordinator.blind_window_liveness_release(evse_id, reason, has_pressure)` which consults the SOC envelope + drain target and writes a `decision_log` row (`decision_type='blind_window_liveness_release'`) for BOTH outcomes so no release is silent. Excess-solar (`determine_excess_solar_actions`) uses CONTINUE-permission semantics: guard engaged + D4 mains-export witness True + envelope lower ≥ drain → already-active EVSEs may CONTINUE; new claims while blind are always refused; any other combination = fail-safe DROP. Ownership honesty (D-LOW-2): a riding EVSE is NOT added to `_paused_by_blind_window`. Each fail-safe defer emits ONE `blind_window_defer` decision_log row per (evse_id, epoch) via dedup on the coord. See PLANNING_ec_blind_window_evse_guard.md and energy_pool.py `_blind_window_guard_engaged` / row 2.5 site. |
| 3 | Breaker safety (grid-charge-on pause) | hardware + battery | energy_pool.py ~:627-646 |
| 4 | Grid-import cap (`_paused_by_grid_cap`) | grid | peer group A |
| 5 | Load shed (`_paused_by_load_shed`) | grid | peer group A |
| 6 | Arbitrage (`_paused_by_arbitrage`) | battery | peer group A |
| 7 | EV battery-drain guard (`_paused_by_battery_drain`) | battery | peer group A |
| 8 | Fill priority (`_paused_by_fill_priority`, SOC < 80) | battery | peer group A |
| 9 | BAEC drain-precedence (`_paused_by_dp`) | battery (deliberate transition) | energy.py `_apply_dp_transition` / `_apply_dp_reversion` |
| 10 | Excess-solar claim (`_excess_solar_active`, SOC>=95 + forecast>=5kWh, never peak) | solar | energy_pool.py `determine_excess_solar_actions` |
| 11 | Off-peak ensure-on (`_proactive_offpeak_holds`) | grid (cheap window) | energy_pool.py ~:569-681 |
| 12 | Peak/mid-peak idempotent OFF | grid | energy_pool.py ~:557-568 |

**BAEC is two-tier:** an ACTIVE carrier state (`transitioned`,
`must_start_forced`, `hold_pre_eval`, `eval_transition`) is a full
peer — nothing below it may claim the EVSE, including excess-solar (a
mid-drain solar spike must not collapse the reserve the drain is
building). A `hold_only` **sticky orphan** (deferred reversion) is
yieldable to excess-solar only — the DP-yield cycle. This yield is
the *only lawful mid-peak escape* for a sticky orphan: the orphan
retry driver calls reversion each tick, but reversion TOU-defers on
anything that isn't off_peak, so on a high-solar mid-peak afternoon
with a full battery, without the yield the car would sit paused all
day (the observed Garage B incident).

**Audit conclusions of record:**
- No reachable state refuses cheap solar while permitting expensive
  grid charging.
- No path drains the home battery into a car outside BAEC's
  deliberate transition window (the captured-SOC hold pins reserve
  under every owner, excess-solar included).
- Owner sets stay SEPARATE by design — collapsing them into one
  priority function was evaluated and rejected (separable ownership
  is what lets framing-disjoint reviews catch distinct leaks;
  v5.5.3 D-HIGH-1 precedent).
- Known accepted follow-ups: force-charge does not release a live
  `transitioned` carrier (MED); no runtime clamp yet between
  `fill_priority_soc` / `excess_solar_soc` / drain targets
  (ladder-validator extension queued); must-start-by does not defer
  on `_paused_by_battery_drain` (corner); excess-solar lacks a
  release-only path when its toggle is off (backlog).

### 2.5a EMERGENCY BACKOUT KNOB — `CONF_RESERVE_VERIFIABLE_MAX_AGE_S` (v5.28.0)

**⚠️ FIRE AXE BEHIND GLASS — read this before ever touching the value.**

The blind-window EVSE guard's entry predicate asks "can we prove a battery
reserve write would take RIGHT NOW?" via `is_reserve_verifiable()`
(`energy_write_verify.py`). Verifiable requires ALL THREE:
(a) record status OK (STALE never counts),
(b) the verified outcome fresher than **`CONF_RESERVE_VERIFIABLE_MAX_AGE_S`
    (default 600 s, rung-1 constant in `energy_const.py`)**, and
(c) the reserve oracle readable at this instant.

**Setting the constant to 0 disables ONLY gate (b).** It exists solely as an
emergency backout: if the freshness gate ever false-positives in production
(guard engaging constantly on healthy telemetry, chargers deferring on good
days), zero it to retreat from the one sub-check without reverting the
cycle. Sequence: zero as stopgap → file the fix-forward cycle → restore 600.

**The documented price at 0 (bounded by the Tier-3 D re-pass):** gates (a)
and (c) survive, so FULL outages (Envoy dark, oracle unreachable — the
2026-07-21 incident shape) remain protected even at 0. The hole reopens
ONLY for PARTIAL outages: SOC feed blind while the reserve oracle still
answers and a resting-OK record exists → predicate reports verifiable →
guard does not arm → pre-v5.28.0 behavior for that window. Full outages
protected; partial outages exposed. This asymmetry is intentional and is
NOT a bug — do not "rediscover" it (review record:
`docs/reviews/code-review/v5.28.0_ec_blind_window_guard.md`).

**For future agents:** never promote this to an options/Number knob; never
zero it as a tuning move; any change to its value or semantics is
Tier 2-DB minimum with the guard test file as the regression harness.
Sibling kill-switch with DIFFERENT semantics: `CONF_BLIND_WINDOW_MAX_DEFER_MIN
<= 0` disables the whole guard (releases pauses, no helper, no rows).

### 2.5 Blind-hold contract (v5.17.5)

Battery telemetry can degrade — local Envoy API stops answering, or
SOC readings go stale. The EC now behaves this way when telemetry is
degraded:

- **True blind (no SOC resolver tier is fresh):** hold in place, do
  nothing risky, log-flag it.
- **Degraded but usable (cloud-fallback tier is fresh):** decide
  normally; state includes a `(degraded telemetry)` suffix so you can
  see the mode from the sensor.
- **Peak blind de-escalation:** during peak with no fresh SOC, revert
  to a safe static reserve and disable charge-from-grid rather than
  guess.
- **Sweep stand-down:** the recovery sweep won't self-heal against
  operator manual changes while stale — so if you turned charge-from-
  grid off yourself, the EC won't turn it back on until it has fresh
  data proving your setting isn't just a stale echo.
- **Breaker guard fails closed:** if the storm-precharge breaker guard
  can't read state, it treats that as "don't precharge".

**v5.17.6 exception:** storm precharge is exempt from the blind freeze
(you want to precharge INTO a storm even if telemetry's shaky), but
bounded by a 30-min SOC-freshness window.

### 2.6 Write model — cloud-first, local as witness (v5.16.x)

Every battery command (`storage_mode`, `reserve_battery_level`,
`grid_enabled`, `charge_from_grid`) is sent via the **Enphase cloud
integration**. The local Envoy API is a **witness** only — it can
observe divergence and log it, but it does NOT write. Rationale: on
Envoy firmware 8.3.x, local writes are accepted-then-ignored (a
discovery post-v5.16.0). Local settings sync is frozen at this
firmware level.

**Write-verify tripwire.** Each command is followed by a verification
read. Three consecutive missed verifies for the same surface
(N=3 self-heal alarm) raises the write-verify anomaly. State
`STATUS_STALE` was retired in v5.17.2 — a stale record now freezes its
`verified_at` timestamp so you can see how old the last good verify was.

---

## 3. Knobs and where they live

Placement follows the "Numbers Get Knobs" ladder
(see CLAUDE.md 2026-07-16): module constant → options flow → Number
entity, based on how often it should legitimately be turned and whether
turning it should require code review.

### 3.1 Number entities (live-tunable from dashboard)

| Number entity | Default | What it does |
|---|---|---|
| `number.ura_energy_coordinator_arbitrage_charge_lead_time_min` | 180 min | How many minutes before peak the grid-charge chunk starts. Recently tuned 360 → 180 organically (v5.17.1 planning notes). Pure knob turn, zero code. |
| `number.ura_energy_coordinator_excess_solar_soc` | 95% | SOC at which surplus solar routes to L2 EVSEs before exporting. |
| `number.ura_energy_coordinator_fill_priority_soc` | (< excess) | Companion pause-until threshold; must be below `excess_solar_soc`. |
| Battery drain targets per solar class | (per-class) | Per-class Numbers set how low the EC will allow the battery to drift off-peak on `excellent / good / moderate / poor / very_poor` days. Legitimate operator tuning based on observation. |
| `switch.ura_energy_coordinator_battery_aware_ev_charging` | ON (since 2026-07-17) | BAEC master switch. OFF = shadow mode (observability only). Mirrors the options-flow toggle live, both directions. |
| `number.ura_energy_coordinator_dp_must_start_by_min_past_midnight` ("Latest charge start") | 180 (03:00) | Car charging always begins by this time regardless of battery drain progress. The only BAEC number left on the device page — the 4 advanced ones (Decision delay, Charging time buffer, Typical charge needed A/B) plus Overnight house load estimate are registry-disabled (re-enable in UI) and live in the options flow instead. |

### 3.2 Options flow (per-deployment structure — infrequent changes)

- TOU schedule bindings (`sensor.pec_current_tou_period` and season
  windows).
- Battery / Enpower entity IDs (cloud + local witness).
- EVSE switch and power-monitor entity IDs.
- Pool VSF and circuit entity IDs.
- Solcast forecast entity IDs.
- **Battery-Aware EV Charging section (v5.21.0):** enable toggle +
  Latest charge start, with a collapsed "Advanced (rarely change)"
  apron for Decision delay, Charging time buffer, Typical charge
  needed — Garage A/B, and Overnight house load estimate. Saves apply
  LIVE (no reload); the enable toggle and the device switch stay in
  sync both directions.
- **Cloud-verification section — D2 detection knobs (v5.21.0,
  promoted from constants):** Battery level disagreement alert
  (pp, default 10, **0 = detection off**), Disagreement confirmation
  time (min, default 5), Cloud update delay alert (s, **0 = alert
  off**, delay still shown on the sensor).

### 3.3 Reviewed constants (change requires code review)

Live in `energy_const.py`. Do NOT expose these as dashboard knobs —
changing them silently would invite untracked drift.

- `SOLAR_MONTHLY_THRESHOLDS` (line 81) — P25/P50/P75 per month.
- `CONSUMPTION_REGRESSION_V1` (line 141) — the v1 fitted regression
  coefficients (temp / season / EV term). Reproducible from a fit;
  making it a knob would defeat that. Currently in SHADOW mode
  (v5.18.0 R1): the estimator computes predictions but legacy
  day-of-week still drives decisions during a 14-day observation.
- `TOU_BOUNDARY_TICK_DELAY_S = 5` (line 196) — the at-boundary tick
  delay past a TOU boundary. **Kill switch:** set `< 0` to disable the
  at-boundary tick and fall back to the pre-v5.17.3 5-minute-aligned
  cadence.
- `R7_USE_UNIFIED_PROJECTOR = True` (line 1144) — v5.18.0 unifies all
  rung/attain projections behind a single `EnergyProjector` primitive
  with no behavior change. Kill switch: set to `False` to fall back to
  per-site projection code paths.

---

## 4. What to watch (sensors and attributes)

The primary dashboard sensor is:

**`sensor.ura_energy_coordinator_battery_strategy`** — state is the
current battery mode (`self_consumption` / `savings` / `backup`); a
`(degraded telemetry)` suffix indicates cloud-fallback tier is
driving decisions. Attributes to watch:

| Attribute | Meaning |
|---|---|
| `arbitrage_phase` | `inactive` / `charging` / `attain` / `solar_attain` — which arbitrage state machine leg is running. `attain` = peak-buffer top-off; `solar_attain` = riding solar toward the target. |
| `peak_buffer_target` | The SOC target the arbitrage chunk is charging toward. |
| `target_day_class` | Today's solar classification (excellent / good / moderate / poor / very_poor). |
| `arbitrage_chunk_completed` | `True` once the completed-chunk HOLD (v5.17.1) has locked reserve until the TOU boundary. |
| `arbitrage_charge_lead_time_min` | Currently effective lead-time knob value. |
| `next_high_rate_transition` | ISO timestamp of the next TOU boundary the EC is planning around. |
| `charge_window_opens_at` | When the arbitrage grid-charge window will open. |
| `forecast_outlook` | Plain-English one-liner ("expect ~28 kWh solar; peak buffer target 60%"). |
| `optimization_summary` | One-sentence "why the battery is doing what it's doing right now" (v4.7.x D4). |
| `current_grid_cost_per_hour` | Live $/hr from current import (0 when exporting). |
| `next_decision_boundary` | Next TOU transition + expected action. |
| `current_holds_active` | Any active holds: `evse_battery_hold`, `arbitrage_compound_load`, `grid_import_cap`, inclement `partial_hold`, blind-hold, etc. |
| `evse_paused_by_arbitrage` | Which EVSE switches are currently paused by EC. |
| `evse_force_charge_until_iso` | If you invoked a force-charge override, when it expires. |
| `control_grid_enabled` / `control_reserve` / `control_mode` | v5.17.0 — the current *commanded* value the EC last wrote (write-verify comparison target). Diverges from the sensor's actual reading = write drift. |
| **Rung / gate attrs (v5.17.2)** | `rung`, `rung_reason`, `attain_projected_soc`, `attain_solar_term_pct` — visibility into the arbitrage_solar_attainability_ladder (rung 0 = short-circuit closed, rung 1 = solar-refill projection, rung 2 = full charge). Projections are now clamped to `[0, 100]` for display (v5.17.4 fix for the 836% artifact). |

Other sensors:

- `sensor.ura_energy_coordinator_energy_battery_decision` — last
  battery decision as a discrete record (arbitrage phase transitions,
  reserve moves, mode changes).
- `sensor.ura_energy_coordinator_arbitrage_savings_today` /
  `_cycle` / `_total` — dollars saved by arbitrage.
- `sensor.ura_energy_coordinator_energy_battery_full_time` —
  projected time-to-full at current charge rate.
- `sensor.ura_energy_daily` — daily energy totals; carries the
  `predicted_consumption_source` marker so you can see whether the
  v1 estimator or the legacy day-of-week baseline drove today (v5.18.0
  SHADOW mode marker).

**`sensor.ura_energy_coordinator_ev_charging_plan`** (v5.20.0) — the
BAEC state machine: `hold_only` → `hold_pre_eval` → `eval_transition` →
`transitioned` → (`must_start_forced`). Attributes: `since`,
`must_start_by_dt`, `last_eval_at`, `last_eval_snapshot` (the arithmetic
behind the latest decision — first place to look when asking "why
did/didn't it transition"), and in shadow mode the `shadow_*` mirrors.
The sibling EVSE status sensor reports `dp_paused` as a distinct pause
reason.

**`soc_resolution`** (attr on battery_strategy, v5.20.0) — which SOC
source is driving (`primary_envoy` / `cloud_fallback` / lkg), per-source
values + ages, `divergence_pp`/`divergence_active`, and
`cloud_settings_lag_s`/`_active`. Both detection legs validated live
2026-07-17 (Envoy dropout → cloud_fallback; cloud lag 2777s → lag
alert active).

### 4.1 Observability WebSocket (v5.17.0)

Read-only HA WebSocket API (`docs/websocket_api.md`) surfaces anomaly
rows and control_* series into the URA PWA without polling. Zero
writes; server-side clamped `limit`; hard-coded column allowlist. Feed
the PWA M4 alerts + activity feed.

---

## 5. How to intervene safely

**Rule of thumb:** if a Number/Switch entity exists for it, turn that.
Don't reach past URA to the Enphase app / Envoy directly unless you're
diagnosing degraded telemetry — the EC will detect the divergence and
may sweep it back (with the v5.17.5 stand-down protecting you if
telemetry is stale).

### 5.1 "The car didn't charge overnight"

1. Check `sensor.ura_energy_coordinator_battery_strategy` attributes:
   is `current_holds_active` empty? Was there an
   `evse_battery_hold` all night?
2. Confirm the drain-pause release ran at off-peak boundary — v5.15.0
   fixed the dead-band where a static floor (10) vetoed against the
   live commanded floor (15–40). If it didn't, capture the log and
   file a regression.
3. Check the EVSE switch entity states directly.

### 5.2 "The battery held at X% all peak and didn't discharge"

- Read `current_holds_active`. Inclement `partial_hold` or
  arbitrage-completed HOLD will legitimately pin reserve high.
- Check `arbitrage_chunk_completed` — if `True`, the v5.17.1 lock is
  in effect until the TOU boundary (this is by design, invariant
  I-AH1).
- Check for `(degraded telemetry)` suffix — blind-hold total contract
  (v5.17.5) will freeze at reserve floor when SOC is truly unknown.

### 5.3 "It grid-charged when the day looked good"

- Check `target_day_class` — the EC may have classified the day
  `moderate` or worse against the monthly P25/P50/P75 threshold. The
  monthly thresholds mean an "80°F sunny day" that's great in December
  is only P50 in June.
- Check `forecast_outlook`.

### 5.4 Tuning arbitrage timing

`number.ura_energy_coordinator_arbitrage_charge_lead_time_min` is the
right knob. 180 min is the current default (down from 360 organically).
Lower = tighter/riskier (may not finish the chunk before peak); higher
= safer margin but you may charge during more expensive minutes.

### 5.5 Excess-solar diversion threshold

`number.ura_energy_coordinator_excess_solar_soc` (default 95). Lower
this to be more aggressive about diverting to EVSEs before export;
raise it to prioritize battery top-off.

### 5.5a EV SOC-threshold jurisdiction — who governs which window

The EVSE SOC knobs are TWO owners' engage points, not one hysteresis
loop. Their non-overlapping shifts across a summer day:

| Window | Governing owner | Behaviour |
|---|---|---|
| Sunrise → 14:00, **SOC < 80** (off-peak daylight) | **Fill priority** (row 8, `fill_priority_soc`=80) | HOLD the car — battery fills first. The ONLY owner between ensure-on and the car here. Releases at SOC 80 → ensure-on charges on cheap off-peak while solar pushes battery toward 95. Fired live 2026-07-23 07:59:55. |
| 80–95 band, daytime | **Plain TOU** | Hands-off; no solar-aware interference either way. |
| **SOC ≥ 95** + forecast ≥ 5 kWh, never peak | **Excess-solar** (row 10, `excess_solar_soc`=95) | Turn ON (overriding TOU pause). Cut off the instant SOC dips **below 95** OR forecast < 5 kWh OR peak starts — NOT at 80. Worst-case battery give-back through this path ≈ 5 SOC points. |
| Peak | TOU pause (row 12) | Battery needed; EV off. |
| Night off-peak | Ensure-on | Cars charge (v5.5.5 deadlock fix; fill-priority inert at night). |

The 80–95 dead band is asymmetric by design: **pause-until 80, resume-at
95** — two owners' thresholds, not a single loop.

**⚠️ Two knobs share the value 80 — do not conflate.**
`fill_priority_soc` (when morning cars wait for the battery) and
`energy_ev_battery_drain_soc` (the blind-window envelope's ride-cut bar,
§2.5a) both default to 80 in this deployment but are INDEPENDENT knobs.
Tuning one does not move the other.

### 5.6 Kill switches

- **Battery-Aware EV Charging:** flip
  `switch.ura_energy_coordinator_battery_aware_ev_charging` OFF (or the
  options-flow toggle — both apply live). Mid-transition OFF reverts
  cleanly: sticky release un-pauses the car once TOU/peers permit, the
  reserve floor collapses when the pause set drains. Feature falls back
  to shadow mode, not silence.
- **D2 divergence detection:** set "Battery level disagreement alert"
  to 0 in the cloud-verification section (detection off, attr cleared);
  "Cloud update delay alert" 0 = alert off, delay still displayed.
- Disable the at-boundary tick: set `TOU_BOUNDARY_TICK_DELAY_S < 0`
  in `energy_const.py`.
- Disable the unified projector: set `R7_USE_UNIFIED_PROJECTOR = False`
  in `energy_const.py`.
- The last two require code change + reload; they exist for
  revert-if-broken, not for routine tuning.

---

## 6. Recent version history (for context)

| Version | What changed (operator-visible) |
|---|---|
| v5.15.0 | EV charge-start dead-band fix (drain-pause reads live commanded floor, off_peak-gated, L1/L2 parity). |
| v5.16.x | All battery writes cloud-first; local Envoy demoted to witness (accepted-then-ignored on fw 8.3.x). Write-verify N=3 self-heal alarm. |
| v5.17.0 | Observability WebSocket API + `control_*` attributes on battery_strategy. |
| v5.17.1 | Tier-3 arbitrage completed-chunk HOLD (invariant I-AH1). `arbitrage_charge_lead_time` Number. |
| v5.17.2 | Rung / gate observability attrs; solar_attain phase; STATUS_STALE retirement. |
| v5.17.3 | At-boundary TOU tick (+5s past the boundary). Kill switch `TOU_BOUNDARY_TICK_DELAY_S < 0`. |
| v5.17.4 | Rung projection solar-horizon bound; [0,100] display clamp (836% artifact fix). |
| v5.17.5 | Blind-hold total contract: true blind = freeze, degraded = decide normally with suffix, peak blind de-escalation, sweep stand-down, breaker guard fails closed. |
| v5.17.6 | Storm precharge exempted from blind freeze (bounded by 30-min SOC freshness). |
| v5.18.0 | R1 consumption-estimator shadow; R7 unified projector; storm-precharge bound. |
| v5.19.0 | Behavioral write-verify: conduct check + pending watchdog + command_trail (caught a real wedge day one). |
| v5.20.0 | Cloud-reliance D2 (soc_resolution tiers, divergence + cloud-lag detection) + Battery-Aware EV Charging shipped dormant (Tier-3: 2 CRIT + 7 HIGH found/fixed pre-deploy). Dead-accumulator recorder exclusion. |
| v5.21.0 | BAEC control surface: options-flow section (live-apply both directions), cognitive-simplicity renames, device slim-down, shadow eval, D2 detection knobs promoted to options. **BAEC ACTIVATED by operator 2026-07-17 ~20:47.** |
| v5.18.0 | R1 consumption estimator v1 in SHADOW (regression + EV term; 14-day observation; `predicted_consumption_source` marker). R7 projection unification (single `EnergyProjector`; kill switch; no behavior change). |
