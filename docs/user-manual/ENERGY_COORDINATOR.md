# Energy Coordinator — User Manual

**Device:** `URA: Energy Coordinator`
**Last updated:** 2026-06-16 (v5.5.1)
**Scope:** every control, sensor, switch, and form field on the Energy Coordinator surface

This is a task-oriented manual: skim the section headings to find what you need, read the troubleshooting recipes when something feels wrong. The reasoning behind each default is included so you can judge edge cases without re-deriving from first principles. Behaviors are cited to source (`file:line`) or shipped release so they're verifiable — this manual does not describe a plausible-sounding mental model, only what the code actually does.

### Changelog — what the v5.5.1 revision added/corrected

This revision brings the manual current from the v4.5.x baseline through the v5.x line:

- **Rewrote §2** — the battery strategy is now an **arbitrage umbrella** with an **attain fill-phase tri-state machine** (v5.3.8) and a **three-rung least-cost ladder** (v5.3.9). The old four-phase WAIT→CHARGE→HOLD→DISCHARGE diagram is preserved as the conceptual frame but the HOLD/attain semantics are corrected.
- **Added §2a** — the three-rung solar-attainability ladder (rung_0 do-nothing / rung_1 pause-EVs-redirect-solar / rung_2 grid-charge). Solar-first, grid-last (v5.3.9).
- **Added §3a** — inclement-weather battery hold (v5.5.0): NWS-alert-driven graduated hold, separate from arbitrage.
- **Corrected the battery SOC + reserve sources** — URA reads the **Envoy** battery sensor (not SPAN), and writes the **enphase_envoy** reserve number. The `iq_battery_hacs`/`enphase_ev` reserve entities are a separate integration's readout, NOT URA's control surface.
- **Updated the switches** — `Excess Solar Charging` was renamed to `EVSE Solar-Aware Charging` (v4.7.6); load-shedding tiers corrected to the actual `[pool, ev, smart_plugs, hvac]` cascade; added the strict EV-TOU + force-charge override.
- **Added §6a** — the v5.3.1 energy-unit-normalization / 4-tier-attribution surfaces (zone/house cost-today sensors).
- **Documented known limitations honestly** — the arbitrage-WAIT partial_hold-floor gap and the misleading secondary reserve entities.

---

## 1. What the Energy Coordinator does

URA: Energy Coordinator is the brain that decides, every 5 minutes, how the house manages its battery, its grid imports, and its surplus solar. It runs several loosely-coupled subsystems under one decision cycle:

- **Battery Strategy** — the arbitrage state machine (WAIT → CHARGE → HOLD → DISCHARGE umbrella) plus the **attain** fill-phase tri-state machine and the **three-rung least-cost ladder** that fill the battery for a forecast high-rate boundary using solar first and grid last (§2, §2a)
- **Inclement-Weather Hold** — a separate, NWS-alert-driven graduated battery hold for power-threat storms (§3a), replacing reliance on Enphase Storm Guard
- **Time-of-Use Engine** — knows which TOU period and rate apply at every moment, including cross-midnight transitions and seasonal switching
- **Solar Forecast** — pulls Solcast (today + tomorrow + remaining) and classifies each day as excellent / good / moderate / poor / very_poor
- **EV Charge Controller** — gates EVSEs by TOU period, battery state, arbitrage/attain mutual-exclusion, and load-shed/grid-cap ownership
- **HVAC Constraint** — feeds offsets and coast/shed/precool/preheat signals into the HVAC Coordinator so climate behavior adjusts to energy state
- **Load Shedding** — a reactive cascading peak limiter: detects sustained grid imports above threshold and walks down a four-tier hierarchy (§3)

The subsystems share the same energy snapshot (refreshed every cycle) and the same circuit monitor (Span / Emporia via the per-circuit integrations you configured). Each subsystem has a master kill-switch.

**Battery hardware:** URA reads battery state of charge from the **Enphase Envoy** (`sensor.envoy_<serial>_battery`, default derived in `energy_const.py:645`; `battery_soc` property at `energy_battery.py:401`). It does **NOT** read SPAN's `battery_level` — SPAN's reading is miscalibrated and is not a configured source. URA actuates the battery by writing the reserve-SOC number `number.enpower_482348004678_reserve_battery_level` (`DEFAULT_RESERVE_SOC_ENTITY`, `energy_const.py:137`), owned by the official `enphase_envoy` integration, plus the storage-mode select and charge-from-grid switch on the same Enpower device. The base reserve floor is **10%** (`DEFAULT_RESERVE_SOC`, `energy_const.py:109`).

> **Caution — misleading secondary entities.** A *separate* battery integration (the `iq_battery_hacs` / `enphase_ev` family) exposes its own reserve-level entities. Those are a **frozen secondary readout from a different integration — not URA's control surface.** URA neither reads nor writes them. If you're diagnosing a reserve change, watch `number.enpower_482348004678_reserve_battery_level`, not the `iq_battery_hacs` reserve entity.

**Decision cadence:** 5-minute polling cycle, plus event-driven response to circuit-level anomalies, EVSE state changes, and Envoy availability transitions.

---

## 2. The battery strategy: arbitrage umbrella + attain fill phase

This is the headliner. The original v4.5.0 four-phase machine (below) is the conceptual frame; v5.3.8 (**attain**) and v5.3.9 (**three-rung ladder**, §2a) refined how the battery actually *fills* for a high-rate boundary. The guiding principle across all of it: **solar-first, grid-last.** URA pulls cheap off-peak grid only when projected solar will not reach the buffer target on its own.

**Terminology — arbitrage vs. attain.** "Arbitrage" is the *umbrella* strategy (buy cheap, displace expensive). "Attain" is specifically the **fill phase** — the tri-state machine (`_run_attain_branch`, `energy_battery.py:2284`) that drives SOC up to `peak_buffer_target` ahead of the next high-rate period and then *pins* it there.

```
                    ┌─────── chunk_completed ───────┐
                    │   (chunk = one off-peak run)  │
                    ▼                                │
  ┌──────┐   gate    ┌────────┐  SOC≥target  ┌──────┐  TOU enters peak/mid_peak
  │ WAIT │ ────────► │ CHARGE │ ───────────► │ HOLD │ ───────────────────────────┐
  └──────┘  opens    └────────┘              └──────┘                            │
     ▲                  ▲                                                       ▼
     │                  │ reverts if forecast improves               ┌─────────────────┐
     │  TOU enters      │ at first WAIT→CHARGE per chunk             │   DISCHARGE     │
     └─ off_peak ───────┴────────────────────────────────────────────│   (existing)    │
                                                                     │   reserve=10    │
                                                                     │   no grid chg   │
                                                                     └─────────────────┘
```

| Phase | When | Reserve SOC | Charge from grid | What it does |
|---|---|---|---|---|
| **WAIT** | Off-peak, before the charge window opens / fill not yet needed | 10 (reserve_soc) | OFF | Battery serves loads naturally. SOC drifts down. |
| **CHARGE** | Off-peak, fill needed, the rung-2 (grid) path selected | peak_buffer_target (default 80) | **ON** | Grid charges the battery. **EV mutual-exclusion engages** — any running EVSE is paused for the duration (breaker protection). |
| **HOLD** (attain `holding`) | SOC reached `peak_buffer_target` during fill | peak_buffer_target | OFF | Reserve **pinned** at target. Solar can still push above target, but grid won't. See attain semantics below. |
| **DISCHARGE** | TOU enters mid_peak or peak | 10 | OFF | Battery covers load, displaces high-rate imports. |

**The attain tri-state machine (v5.3.8, `energy_battery.py:2284-2413`).** The fill phase is a three-state machine: `inactive → charging → holding`.
- `inactive` — the entry predicate (solar projection + floor + rate gate) may fire and move to `charging`.
- `charging` — verify-only maintenance; transitions to `holding` the moment SOC reaches `peak_buffer_target`.
- `holding` — **re-emits a HOLD decision EVERY tick** (reserve pinned at `peak_buffer_target`, `charge_from_grid=False`; `energy_battery.py:2042-2043`). Crucially, **if SOC sags below target while holding, it STAYS holding** — the pinned reserve floor holds the battery up; it does not drop back to `charging` and re-pull grid. Holding is routed *before* the entry predicate and the chunk-lock, and exits only via the boundary handoff (within `ATTAIN_PEAK_HANDOFF_LEAD_MIN = 15` min of the high-rate boundary, the HOLD continues until the TOU branch takes over) or the charge window closing.

**Charge window timing:** `charge_start_time = next_high_rate_transition − arbitrage_charge_lead_time_min`. Default lead time is 360 min (6 hr). Biases toward earlier start so intraday Solcast updates (which accumulate from sunrise) can re-classify the target day. Hard min 120 min, hard max 720 min.

**Per-chunk lock:** one fill cycle per off-peak chunk. Resets on TOU transition INTO off_peak. Prevents oscillation if SOC dips post-completion or the forecast wobbles.

**Solar-informed entry / forecast re-check:** the entry predicate consults the projected solar surplus (`_expected_solar_surplus_pct`, `energy_battery.py:1636`), which nets house load via `SOLAR_CAPTURE_FACTOR = 0.5` (`energy_battery.py:87` — a deliberately conservative constant: only ~half the remaining-day Solcast forecast is assumed to land in the battery before the boundary). If tomorrow's forecast classifies well enough that solar alone will reach target, the grid fill is suppressed. Stale/unavailable Solcast → surplus treated as 0 (fail toward charging — buffer matters more than a wasted cheap charge).

---

## 2a. The three-rung least-cost ladder (v5.3.9)

**Why it exists.** On an excellent-solar morning (17 kW, net exporting, grid effectively $0), the old code would still fire a grid CHARGE *and pause both EVs* — burning money and blocking the cars while the sun would have filled the battery for free. The ladder (`_classify_attain_rung`, `energy_battery.py:1060-1085`) picks the **least-cost intervention** that still reaches `peak_buffer_target` at the boundary. It runs a two-pass projection each arbitrage-eligible tick:

| Rung | Label | Condition | Action |
|---|---|---|---|
| **rung_0** | (none) | Today's solar **+ current loads (EVs included)** projects SOC ≥ target+hysteresis at the boundary | **Do nothing.** Arbitrage gate stays CLOSED, EVs keep charging on solar, no grid. |
| **rung_1** | `redirect` | rung_0 misses, but re-projecting with the **EV load removed** attains target | **Pause EVs only** to redirect their solar into the battery. Grid stays closed. |
| **rung_2** | `breaker` | Even with EVs paused, solar misses | **Grid charge** (`charge_from_grid=True`) — the LAST resort. EVs also paused, for compound-load (main-breaker) protection. |

**Solar-first, grid-last** is the whole point: grid is only pulled at rung_2, and only when neither doing-nothing nor redirecting EV solar would reach the target in time.

**No oscillation (the counterfactual exit).** While latched at rung_1 the EVs are paused, so the observed net-charge rate is artificially inflated (their load is gone). A naive re-check would read "solar attains now" → resume EVs → load returns → miss again → re-pause: bang-bang. So the rung_1 **exit is counterfactual** — it re-adds the EV load into the projection and only drops to rung_0 / resumes the EVs if solar *still* attains with the cars charging. This is a stable latch, mutation-guarded by a 5-tick oscillation test.

**Cold boot:** until the trailing rate window has ≥2 samples, the ladder conservatively returns rung_2 (same shape as the attain cold-boot defer).

**Breaker-safety chokepoint (D2).** A 20 kW grid charge + a charging EV + base load ≈ 134 A → main-breaker trip. A single dispatch-site chokepoint, keyed on the decision's `charge_from_grid` flag (so it covers arbitrage CHARGE, attain, AND rung_2 uniformly): no `charge_from_grid=True` fires until EVs are commanded paused in the same tick, and no EV is commanded ON while grid charge is on. The guard reads the **decision flag OR the live switch** (covering the ~35-min Enphase actuation lag), fails CLOSED on `unavailable`, and re-establishes the pause from the live switch after a reboot-mid-charge.

**Observability:** no new config or entities — the ladder surfaces via the existing `arbitrage_phase`/`reason` plus a `paused_by_arbitrage_reasons` attribute (`redirect` vs `breaker`) on the EV diagnostic sensor.

---

## 3. The kill-switches (master toggles + sub-feature toggles)

Seven switches live on the URA: Energy Coordinator device page. **The 5 sub-feature switches require the EC coordinator to have started successfully** — if Envoy validation fails at boot (entity missing / unparseable serial / critical derived entities not registered), all 5 sub-switches show `unavailable` until the coord recovers. Master `Enabled` and `Observation Mode` stay available regardless.

### `Enabled`
**Default:** ON
**What it does:** master enable for the entire Energy Coordinator. When OFF, the decision cycle still runs (and records measurements for sensors) but issues **no commands** to Envoy, EVSEs, or HVAC. All actuation paths short-circuit.
**When to disable:** during major utility-meter events, hardware swaps, or whole-house diagnostic sessions where you want URA's sensors to keep observing but not act.

### `Observation Mode`
**Default:** OFF
**What it does:** softer than `Enabled = OFF`. The coordinator still computes decisions but **stops actuating Enphase storage mode + reserve SOC + charge-from-grid**. EVSE controls and HVAC constraints continue to flow. Useful for confirming the strategy matches your intuition before letting it commit.
**When to enable:** first 1–2 weeks after major config changes (new TOU schedule, new Solcast credentials, new arbitrage settings) so you can verify the *intent* of every decision before it touches your battery.

### `Grid Import Cap`
**Default:** OFF
**What it does:** when ON, every decision tick the coordinator compares live net grid import (from Envoy's net-power sensor) against the configured `energy_grid_import_cap_kw` (3-20 kW, default 8 kW, configured via options-flow slider). If import exceeds the cap, **any actively charging EVSE is paused** (`switch.turn_off`). Resumes only when import drops below `cap_kw − 1.0 kW` (hysteresis band).
**Acts on EVSEs only.** Non-EV loads (HVAC, water heater, plug loads) are NOT throttled — if they alone exceed the cap, the diagnostic sensor `sensor.ura_energy_coordinator_energy_grid_demand` shows >100% but URA takes no action.
**Tracked independently from TOU pausing** — an EVSE can be paused-by-TOU AND paused-by-cap simultaneously; resume only fires when neither flag is set.
**When to enable:** if your service has a real hard limit (e.g., 60A DER breaker → ~14 kW continuous). Set the cap a few kW below the breaker rating.

### `Load Shedding`
**Default:** OFF
**What it does:** enables a **reactive cascading peak limiter** — when sustained grid import exceeds the configured threshold for the sustained-minutes window, it walks down a four-tier priority list (`LOAD_SHEDDING_PRIORITY = ["pool", "ev", "smart_plugs", "hvac"]`, `energy_const.py:610`): tier 1 = pool pump speed reduction, 2 = EV chargers off, 3 = smart plugs off, 4 = HVAC energy-constraint signal (coast/shed offset to HVAC). Recovery is reverse order when import drops back below threshold. Defaults: threshold **5 kW** (`energy_const.py:595`), sustained **15 min** (`energy_const.py:596`).
**Pause-ownership is isolated (v5.4.1):** shed-paused EVs and plugs live in a dedicated `_paused_by_load_shed` set, so a sibling owner (TOU pause, arbitrage, grid-cap, solar-aware) can't turn a shed device back on, and shed release defers to every other owner. Orphan-restore survives a watchdog kill (state persists as an atomic JSON bundle); manual-off-wins (a device you turned off mid-shed stays off; one you turn back on gets re-shed).
**Different from Grid Import Cap:** load-shedding is a graduated four-tier cascade; grid-import-cap is a simple binary on/off acting only on EVSEs. The cap fires faster (1 decision tick) and finer (only EVSEs); load shedding requires a sustained breach and walks down the hierarchy.

### `EVSE Solar-Aware Charging`
**Default:** OFF
**Entity:** `switch.ura_energy_coordinator_evse_solar_aware_charging`
**Renamed (v4.7.6):** this was previously `Excess Solar Charging` (`switch.ura_energy_coordinator_excess_solar_charging`). The history/unique_id is preserved (`{DOMAIN}_energy_excess_solar`) so your statistics survived the rename (`switch.py:46-69`).
**What it does:** when ON and battery SOC ≥ `energy_excess_solar_soc` (default 95%) AND remaining today solar ≥ `energy_excess_solar_kwh` (default 5 kWh) AND current TOU is off-peak or mid-peak (never peak), **turn ON EVSEs** to absorb surplus solar that would otherwise be exported. Only turns off EVSEs that URA itself turned on — won't fight a user who manually started charging.
**When to enable:** if your utility's net-metering doesn't credit exports as well as import-displacement (asymmetric rates), or if your battery is small relative to your daily PV production.

### `Grid Arbitrage`
**Default:** OFF
**What it does:** master enable for the battery fill machinery — the attain tri-state machine (§2) and the three-rung ladder (§2a). On poor-solar-tomorrow days (`classify_tomorrow_solar` returns `poor`/`very_poor`, `energy_battery.py:556`) the charge window opens, and the ladder fills the battery using the least-cost rung — doing nothing if solar alone will reach target, pausing EVs to redirect solar if that's enough, and only pulling `charge_from_grid` as the last resort.
**Gated by `Peak Buffer Target`** — fill stops (enters attain HOLD) when SOC reaches the target.
**Inclement-weather hold takes priority** — if an active power-threat NWS alert is holding the battery (§3a), that path runs instead.

### `EV TOU Management` — strict policy behavior (v4.7.x)
**Default:** ON
**What it does:** when ON, URA pauses all EVSEs during peak and mid_peak TOU periods. **This is a strict, idempotent policy** — if you manually re-enable an EVSE switch in HA, URA will turn it off again on the next decision cycle (≤5 min). Manual HA-side EVSE toggles are intentionally defeated.
**Rationale:** "All grid charging for EV should happen only during off-peak for every season." The strict enforcement prevents cost leaks caused by accidental or casual EVSE re-enables during high-rate periods.
**Exception:** excess-solar charging (when battery ≥95% and solar forecast surplus ≥5 kWh) is still allowed during mid_peak — the switch is ON and URA leaves it running.
**Admin override:** use `button.ura_energy_coordinator_evse_force_charge_30min` for intentional mid-peak charging (see §10 below).

Master gating order — **strict precedence**:

```
1. Envoy unavailable              → hold state, no commands fire
2. Grid disconnected               → BACKUP storage mode
3. Inclement-weather hold active   → full_hold (BACKUP) / partial_hold (elevated reserve floor)
4. Peak / mid_peak TOU             → DISCHARGE logic
5. Off-peak                        → attain fill (rung ladder) OR drain-target fallback
```

Don't re-order these in custom automations layered on top — the precedence prevents combinations like "BACKUP + arbitrage charge" that would fight each other.

---

## 3a. Inclement-weather battery hold (v5.5.0)

A **separate** subsystem from arbitrage — it holds the battery as backup ahead of a power-threat storm, replacing reliance on Enphase Storm Guard (cloud-only, no local veto, blunt 100% grid pre-charge, multi-day stale locks). Config lives under **Energy → Weather Providers** (`inclement.py`; CONF keys `energy_const.py:204-215`).

**Detection — event-type relevance is the PRIMARY gate.** URA parses your NWS Alerts sensor (`CONF_INCLEMENT_NWS_ALERTS_ENTITY`) and gates first on the **Event name**: only events matching the operator-curated power-threat list (`DEFAULT_INCLEMENT_POWER_THREAT_EVENTS` — Tornado, Severe Thunderstorm, Ice Storm, Winter Storm, High Wind, Extreme Wind, Hurricane, Blizzard; `energy_const.py:224`) can ever hold the battery. **Severity is only a secondary noise filter** (default min "Severe"), never the gate. So a `Flood Watch` (Severity=Severe) fails the gate → NOTICE → battery discharges normally. *This is the "beats Enphase" property — Enphase Storm Guard would hold; URA does not.*

**Graduated hold-depth ladder — not a binary hold:**
| Rung | What it does |
|---|---|
| `full_hold` | Short-circuit to BACKUP storage mode (highest-confidence threat) |
| `partial_hold` | TOU branches still run, but with an elevated reserve floor (default **50%**, `CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR`, `energy_const.py:238`) |
| `allow_discharge` | No override — byte-identical to a no-storm tick |

The rung is matrix-driven by **(confidence tier × current TOU period × solar-recovery horizon)**. The operator thesis: a warning at 8am with a sunny day ahead means something different from a warning at dusk heading into a 6–12h overnight outage.

**Solar-horizon recoverability (surplus-based, net of house load).** A mid_peak/peak discharge counts as "recoverable" only if projected solar surplus (the same `_expected_solar_surplus_pct` primitive used by attain, already net of house load via `SOLAR_CAPTURE_FACTOR=0.5`) exceeds what `partial_hold` would permit by a margin (default 5 %SOC). off_peak callers short-circuit (holding forgoes no arbitrage discharge there).

**Hold duration = the alert's own Expires/Ends — the stale-lock fix.** No fixed timer anywhere. Each contributing alert's `min(Ends, Expires)` bounds the hold, re-evaluated every tick, so a hold cannot outlive its alert (directly fixing the Enphase multi-day stale lock).

**No grid pre-charge by default.** `CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD` defaults **False** (`energy_const.py:237`) — URA never burns grid energy to backup-fill on a watch (solar-first). EVs: a charging EV's backup relies on the existing `_apply_evse_battery_hold` reserve clamp (which, per the v5.5.0 EV-audit §2 fix, can only **raise** the reserve, never lower it); this cycle pauses no EVs.

**Observability:** `sensor.ura_inclement_state` (dedicated entity added in v5.5.1) plus inclement attributes on the battery-strategy sensor (`inclement_tier`, `inclement_hold_depth`, `inclement_gated_out_events`, `inclement_solar_horizon`, `inclement_reserve_floor`, `inclement_grid_precharge`) and `SIGNAL_INCLEMENT_STATE_CHANGED`.

> **Setup note:** the feature stays dormant until `CONF_INCLEMENT_NWS_ALERTS_ENTITY` is wired to your NWS Alerts sensor in Energy → Weather Providers options. With no entity set (or no active alert), the resting state is `inclement_tier=none`, `hold_depth=allow_discharge`, `inclement_reserve_floor` == base `reserve_soc` (10).

---

## 4. Runtime sliders (Number entities)

Every Number entity on the Energy Coordinator device is **runtime-tunable** — change the slider value and the next decision cycle picks it up. No reload needed. The slider's value survives HA restart (RestoreEntity-backed). Form-level CONF values are install-time seeds only.

### `Peak Buffer Target` — 30–95%, default 80%
The SOC target that arbitrage CHARGE drives to. Higher means more buffer for peak displacement but more grid imports during off-peak; lower means less stress on the grid but smaller peak coverage.
**Raise** for higher-cost peak periods where every extra kWh of buffer pays back.
**Lower** if you're frequently hitting the grid-import guard during CHARGE or if utility export rates make holding a smaller buffer more economical.
**Note:** values below 30% defeat the purpose (battery won't cover meaningful peak load). Values above 95% stress the battery and rarely complete in time.

### `Arbitrage Charge Lead Time` — 120–720 min, default 360 min (6 hr)
How early (before the next high-rate transition) the charge window opens. Earlier means more time to absorb intraday Solcast updates and adjust; later means less off-peak grid energy spent on a forecast that might still change.
**Raise** if you frequently see arbitrage abort mid-CHARGE because forecast improved. Earlier lead time biases the re-check before commitment.
**Lower** if you observe CHARGE running deep into the high-rate window (rare — usually means the lead time is wrong or grid-import guard is throttling).
**Why `NumberMode.BOX` not slider:** minute-precision values are easier to type than drag. Single decision-cycle worth of granularity matters.

### `Off-Peak Drain Excellent` / `Good` / `Moderate` / `Poor` — 5–80% (per slider), defaults 10 / 15 / 20 / 30
The SOC drain target during off-peak hours, by solar day class. When the next day's solar forecast classifies as excellent, the battery is allowed to drain lower (because tomorrow's PV will refill it for free); on poor days the drain target stays higher so tomorrow's peak still has coverage.
**Tune by climate:** in summer with consistent solar, lower drain targets across the board. In winter with variable solar, raise them.
**One slider per day class** — four sliders. Set them in order of aggression (excellent < good < moderate < poor) or arbitrage logic will warn.

### `EV Battery Drain SOC` — 30–80%, default 50%
The SOC floor at which EV charging from house battery is allowed to start consuming battery (versus pulling from grid). Lower means "fill the EV from battery as long as battery has more than X%"; higher means "preserve the house battery, charge the EV from grid only."
**Raise** if you have a small house battery and a large EV — protects house from being drained by EV.
**Lower** if you have generous PV + storage and want to maximize self-consumption.

---

## 5. Form fields (configured once, at install)

These are set in **Coordinator Manager → Energy** at install time. Most are entity-pickers pointing at your hardware integrations. Changing them requires a reload to take effect.

### Required hardware sensors
| Field | What to set it to |
|---|---|
| **Solar Production Entity** | Enphase Envoy production sensor in kW (e.g., `sensor.envoy_current_power_production`) |
| **Net Power Entity** | Whole-house net kW (positive = importing from grid; negative = exporting) |
| **Battery SOC Entity** | Battery state-of-charge sensor in % — the **Envoy** battery sensor (`sensor.envoy_<serial>_battery`), auto-derived from the Envoy serial. **Not** SPAN's `battery_level` (miscalibrated). |
| **Battery Power Entity** | Battery charge/discharge kW |
| **Grid Import Sensor** / **Grid Export Sensor** | Cumulative kWh totalizers from your utility meter or Envoy |
| **Envoy Entity** | The Enphase Envoy gateway device entity (used as availability proxy) |
| **Lifetime Consumption / Production / Net Import / Net Export / Battery Charged / Battery Discharged** | Six lifetime-cumulative kWh sensors for billing accuracy and arbitrage savings math |

### Solcast forecast
| Field | What to set it to |
|---|---|
| **Solcast Today Entity** | `sensor.solcast_pv_forecast_forecast_today` (typical) |
| **Solcast Remaining Entity** | `sensor.solcast_pv_forecast_forecast_remaining_today` |
| **Solcast Tomorrow Entity** | `sensor.solcast_pv_forecast_forecast_tomorrow` |
| **Solcast Day 3 Entity** *(optional, v4.5.0+)* | `sensor.solcast_pv_forecast_forecast_day_3` — enables D+2 awareness |
| **Solar Classification Mode** | `percentile` (recommended; uses month-aware thresholds) or `fixed` |
| **Solar Threshold Excellent / Good / Moderate / Poor** | The kWh-per-day boundaries between classes. Defaults track your local climate's percentiles. |

### EV / EVSE
| Field | What to set it to |
|---|---|
| **EVSE A Entity** / **EVSE B Entity** | Switch or input_boolean controlling each charger (Enphase IQ EV, Wallbox, etc.) |
| **L1 Charger Entities** | List of low-power EV chargers that don't trigger mutual-exclusion |

### Optional
| Field | What to set it to |
|---|---|
| **Weather Entity** | Used for storm-forecast detection (BACKUP precedence rule) |
| **Generator Entity** | If you have one — used for backup-runtime calculations |
| **Utility Meter Entity** | If your utility provides a smart-meter integration separate from Envoy |
| **TOU Rate File** | Path to your utility's TOU schedule JSON (lives in `/config/`) |

### Load shedding (cascade)
| Field | What to set it to |
|---|---|
| **Load Shedding Enabled** | Master toggle (also exposed as `switch.ura_energy_coordinator_load_shedding`) |
| **Load Shedding Threshold (kW)** | Grid-import kW that triggers shed (default 5 kW; can also be `auto` for 90th-percentile auto-learn after 30+ days of data) |
| **Load Shedding Sustained Minutes** | How long the import must exceed threshold before shed fires (default 15 min) |
| **Load Shedding Mode** | `fixed` or `auto_learned` (the threshold-determination method) |

### Grid Import Cap (single-tier, EVSE-only)
| Field | What to set it to |
|---|---|
| **Grid Import Cap Enabled** | Master toggle (also exposed as `switch.ura_energy_coordinator_grid_import_cap`) |
| **Grid Import Cap (kW)** | Slider 3-20 kW, default 8 kW. Acts only on EVSEs. 1.0 kW hysteresis is hardcoded. |

### Excess Solar Charging
| Field | What to set it to |
|---|---|
| **Excess Solar Enabled** | Master (also `switch.ura_energy_coordinator_excess_solar_charging`) |
| **Excess Solar SOC Threshold** | Battery SOC at which excess-solar EVSE activation is allowed (default 95%) |
| **Excess Solar kWh Threshold** | Remaining today's forecast solar that triggers (default 5 kWh) |

### HVAC constraint offsets
The HVAC Coordinator reads these to know how aggressively to coast / precool / preheat based on energy state.
| Field | Default | Effect |
|---|---|---|
| **Coast Offset** | +1.5°F | When coasting (high battery, excess solar), let setpoints drift this much |
| **Pre-Cool Offset** | −1.5°F | When pre-cooling for forecasted peak, drop setpoints by this much |
| **Pre-Heat Offset** | +1.5°F | Symmetric for heating |
| **Shed Offset** | +3.0°F | When load shedding fires, widen setpoints by this much |
| **Pre-Heat Temp Threshold** | 35°F | Forecast-low below which pre-heat fires |

### Arbitrage
| Field | What it does |
|---|---|
| **Arbitrage Enabled** | Master for the attain fill machine + three-rung ladder (§2, §2a) |
| **Grid Import Guard kW** | Hard cap on non-battery grid import during CHARGE (default 12 kW, 60A-breaker sized; `_grid_import_guard_triggered`, `energy_battery.py:1047`) |
| **Excess Solar Enabled / SOC / kWh** | The EVSE Solar-Aware Charging knobs (see §3 switch) — routes surplus solar to EVSEs above the SOC threshold when the remaining-day kWh budget allows |

### Inclement weather (Energy → Weather Providers)
| Field | CONF key | Default | What it does |
|---|---|---|---|
| **NWS Alerts entity** | `inclement_nws_alerts_entity` | (unset → dormant) | The NWS Alerts sensor URA parses for power-threat events |
| **Power-threat events** | `inclement_power_threat_events` | Tornado, Severe Thunderstorm, Ice Storm, Winter Storm, High Wind, Extreme Wind, Hurricane, Blizzard | The event-name allowlist (PRIMARY gate) |
| **Min severity** | `inclement_warn_min_severity` | Severe | Secondary noise filter, applied after the event gate |
| **Grid pre-charge on hold** | `inclement_grid_precharge_on_hold` | False | Whether to burn grid to backup-fill (solar-first by default) |
| **Partial-hold reserve floor** | `inclement_partial_hold_reserve_floor` | 50% | Elevated reserve during a `partial_hold` |
| **Recoverable surplus margin** | `inclement_recoverable_surplus_margin_pct` | 5 %SOC | Margin solar surplus must exceed to count a discharge "recoverable" |
| **Condition corroboration mode** | `inclement_condition_corroboration_mode` | (named-bucket) | Local multi-provider condition cross-check |

---

## 6. Sensors — what to watch

The Energy Coordinator device hosts 40+ sensors. These are the ones to put on a dashboard:

### Daily snapshots
- **`Battery Strategy`** — current 4-phase state (WAIT / CHARGE / HOLD / DISCHARGE / BACKUP). The single most important signal for "what is the battery doing right now?"
- **`Solar Day Class`** — today's and tomorrow's class (excellent / good / moderate / poor / very_poor). Drives drain targets and the arbitrage gate.
- **`TOU Period`** — current period (off_peak / mid_peak / peak). Use this for automations.
- **`TOU Rate`** — current $/kWh.
- **`Current Rate`** / **`Delivery Rate`** — the rate URA used in the last cost calculation (sanity check).
- **`Situation`** — high-level state machine label combining energy state + occupancy state (used by HVAC).

### v4.6.8 canonical rate + cost surfaces

| Sensor | Value | Notes |
|---|---|---|
| `sensor.ura_energy_coordinator_current_effective_rate` | Current effective $/kWh (base + delivery + transmission) | Read this for "what I pay if I import right now" |
| `sensor.ura_energy_coordinator_zone_<zone>_cost_today` | Per-zone cost from per-zone-power × TOU rate | v4.6.8 |
| `sensor.ura_energy_coordinator_whole_house_cost_today` | House cost rollup | v4.6.8 |
| `sensor.ura_energy_coordinator_zone_<zone>_cost_per_hour` | Live $/h burn rate per zone | v4.6.8 |

**Why this matters:** prior to v4.6.8, multiple call sites computed cost from different rate lookups (some forgot delivery+transmission). The reconciliation made `TOURateEngine.get_effective_import_rate(now)` the single source of truth. All zone/house/appliance cost math now agrees.

### v5.3.1 energy-unit normalization + 4-tier attribution

A live audit on 2026-06-09 found zone/room energy sensors poisoned by a 1000× unit mismatch (Wh summed as kWh — e.g. a zone reading 1,671 kWh "today" at a ~1 kW draw) and lifetime counters leaking into today-scope equations (coverage delta of −839M kWh; attribution coverage of 24-billion %). v5.3.1 fixed it:

- A shared `energy_state_to_kwh` helper (`domain_coordinators/_units.py`) normalizes Wh/kWh/MWh at every energy read; a one-shot version-gated baseline reset cleared the poisoned anchors.
- Coverage-delta tiers (zone / house-device / whole-house) are now **today-scoped** via in-memory midnight-anchored baselines, with per-sensor cumulative-vs-today classification.
- `coverage_rating` gained an **"Anomalous"** verdict (delta < −2% or > 100%) and **"Incomplete"** during the post-restart re-anchor window, so a poisoned reading can no longer be rated "Excellent".
- Rooms whose energy sensors are all dead now report `energy_today = None` (not a silent 0.0) with `energy_sensors_dead: true` and a rate-limited WARNING.

If a zone shows an implausible cost/energy figure, check `coverage_rating` for "Anomalous" and look for `scope_mismatch_warning` / `energy_sensors_dead` attributes before suspecting the rate engine.

### Today + cycle accounting
- **`Energy Import Today`** / **`Energy Export Today`** — kWh totals reset at midnight.
- **`Cost Today`** / **`Cost Cycle`** — dollar totals (daily, billing-cycle).
- **`Predicted Bill`** — current month's bill prediction based on consumption pace + rate schedule.

### Forecast + accuracy
- **`Forecast Today`** / **`Forecasted Import`** / **`Forecasted Consumption`** — what the day is expected to look like.
- **`Forecast Accuracy`** — rolling 30-day comparison of forecast vs actual. Calibration signal.
- **`Battery Full Time`** — estimated time-of-day when battery will hit 100% (or "not today" if not).

### Arbitrage savings
- **`Arbitrage Savings Today`** / **`...Cycle`** / **`...Total`** — estimated $ saved by arbitraging off-peak → peak. Counterfactual: charge_kWh × (peak_rate − off_peak_rate) × round_trip_efficiency.

### EV + circuits
- **`EV Charging Status`** — per-EVSE state (idle / charging / paused_by_arbitrage / paused_by_tou / paused_by_grid_cap).
- **`EV Charge Rate A`** / **`EV Charge Rate B`** — live A/B charger output.
- **`Circuit Anomaly`** — z-score detection on each Span/Emporia circuit. Surface as a notification target.

### Diagnostics
- **`Battery Decision`** — the most recent decision-cycle reason text. Read this to understand why the battery is in its current state.
- **`Load Shedding`** — current shed level (0–3) and reason.
- **`Envoy Status`** — Enphase availability + last-known communication time.
- **`Pool Optimization`** — pool-pump schedule optimization status (if you have one).
- **`Generator Status`** — backup runtime + fuel estimate.

---

## 7. Three-layer gating model

The same shape used elsewhere in URA:

```
┌──────────────────────────────────────────────────────────────┐
│  Master switch (Enabled, Observation Mode)                   │
│    ↓ OFF/Observation → no actuation                          │
│    ↓ ON → evaluate next layer                                │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│  Feature toggles (Arbitrage Enabled, Load Shedding Enabled,  │
│  Excess Solar Enabled, Multi-Day Horizon, Grid Import Cap…)  │
│    ↓ OFF → that subsystem skipped                            │
│    ↓ ON → evaluate per-decision logic                        │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│  Per-decision gates                                          │
│    ↓ (TOU period, SOC, forecast class, storm, Envoy avail…)  │
│    ↓ All gates pass → command fires                          │
└──────────────────────────────────────────────────────────────┘
```

---

## 7a. Known limitations (documented honestly)

- **Arbitrage-WAIT can briefly bypass the inclement `partial_hold` floor** (MEDIUM, tracked follow-up; `energy_battery.py:1521`). When the arbitrage gate is open (tomorrow's solar poor/very_poor) *and* an uncorroborated power-threat **watch** is active overnight, the arbitrage WAIT phase returns `reserve_level = reserve_soc` (10), ignoring the elevated 50% floor. **Not a regression** — it is the build's original shape, and exposure is small (when tomorrow is poor, arbitrage is *filling the battery up* for the bad solar day, which itself serves backup; WAIT is a transient hold). The proper fix threads the floor through the arbitrage/attain state machine and is scoped as its own Tier-2-DB cycle. *Do not flag a brief reserve dip to 10 during arbitrage WAIT + an active uncorroborated watch as a violation — it is a known, accepted gap for v5.5.x.*
- **Misleading secondary reserve entities.** The `iq_battery_hacs` / `enphase_ev` reserve-level entities are a *different* integration's frozen readout and are **not** URA's control surface. URA's reserve control is `number.enpower_482348004678_reserve_battery_level` only (see §1 caution).
- **HA long-term statistics keep the historical 1000× datapoints** from the pre-v5.3.1 unit bug (cosmetic; ages out per recorder retention). Accepted for a single-user install.
- **Upstairs/Outside zone energy recovery requires a SPAN circuit entity_id remap** — operator config work (hygiene bucket), not a code fix. v5.3.1's D4 makes the dead-sensor failure visible (`energy_sensors_dead: true`) meanwhile.

---

## 8. Troubleshooting

### "Arbitrage charged but battery drained back down before peak"

This was the v3.11.0 bug v4.5.0 fixed and v5.3.8 hardened with the attain HOLD. If it's still happening:
1. Confirm you're on v5.3.8 or later (manifest / About page).
2. Check **Battery Strategy** sensor and its `attain_state` attribute: between fill-complete and mid_peak start it should be `holding` (reserve pinned at `peak_buffer_target`, `charge_from_grid=False`). In `holding`, SOC sagging below target is *expected and harmless* — the pinned reserve floor holds the battery up; it does not drain back down past the floor.
3. If `attain_state` is NOT `holding` there, the fill cycle may have fallen through to the drain-target fallback. Check the **Battery Decision** sensor reason text and confirm the off-peak drain slider for the current day class isn't set absurdly low.

### "Arbitrage CHARGE never fires when it should"

1. Confirm **Arbitrage Enabled** switch is ON.
2. Check **Solar Day Class** sensor — the gate only opens when target day classifies as `poor` or `very_poor` (or D+2 with Multi-Day Horizon ON).
3. Check **Arbitrage Charge Lead Time** — if too short, the charge window may never have opened before the high-rate transition arrived.
4. Check **Battery Decision** sensor — it logs the gate reason ("forecast improved on recheck" / "chunk_completed" / "Envoy unavailable" / etc.).
5. Per-chunk lock: only one arbitrage cycle per off-peak chunk. If the chunk completed earlier, the next attempt won't fire until TOU re-enters off_peak.

### "EV stopped charging unexpectedly during off-peak"

Most likely the arbitrage mutual-exclusion paused it during CHARGE phase.
1. Check **EV Charging Status** sensor — if it says `paused_by_arbitrage`, that's the cause.
2. Check **Battery Strategy** sensor — was the state CHARGE during the pause?
3. EV will resume automatically when battery hits HOLD or DISCHARGE.
4. To opt out: temporarily disable **Arbitrage Enabled** for that off-peak chunk. The EV will resume immediately.

### "Cost Today seems way off vs my utility bill"

1. Confirm **TOU Rate File** is current — utility rate plans change.
2. Check **Forecast Accuracy** sensor — if it's been drifting for >2 weeks, the consumption model may be miscalibrated.
3. Lifetime sensor consistency: divergence between Envoy "today" and URA's lifetime-delta indicates a snapshot stale-ness issue, logged as a WARNING. Common after Envoy reboots — usually self-corrects within 24 hr.
4. Verify your **Delivery Rate** matches your utility's posted delivery charge. URA's `delivery_rate` is a separate slider from the energy rate.

### "Solar Day Class always says 'moderate' even on sunny days"

1. Confirm **Solcast** entities are populated (not `unavailable`). Solcast occasionally rate-limits or expires API keys.
2. Check **Solar Classification Mode** — if set to `fixed`, the thresholds might be wrong for your kW system. Switch to `percentile` for month-aware classification.
3. Solar Thresholds (Excellent / Good / Moderate / Poor) should match the seasonal kWh ranges of your PV system. Use 30 days of historical production data to calibrate.

### "Excess solar isn't routing anywhere even though I'm exporting kWh"

1. Confirm **Excess Solar Enabled** is ON.
2. Check **Excess Solar SOC** — surplus routing only fires above this SOC (default 95%). Below threshold, surplus charges the battery instead.
3. Check **Excess Solar kWh** — daily budget. If exhausted, routing pauses until midnight rollover.
4. Look at the destination — the heat pump / pool pump / thermal-banking target must be configured separately (not part of EC; lives in HVAC or pool integrations).

### "Load shedding never fires even when I see big grid imports"

1. Confirm **Load Shedding Enabled** is ON.
2. Confirm **Load Shedding Mode** is `actuate` (not `advisory` — advisory only updates the sensor without broadcasting).
3. Check **Load Shedding Threshold** — sustained ≥ threshold for `Sustained Minutes` is required. A 10-second spike won't trigger.
4. Look at the **Load Shedding** sensor — it logs `imports_above_threshold_for=X.Xmin` so you can see how close you are.

### "Observation Mode is on but the battery still changes mode"

Observation Mode stops **actuation** to Enphase's storage_mode / reserve_soc / charge_from_grid. It does NOT stop:
- TOU-driven battery behavior (which Enphase manages locally based on its own profile)
- EV controls (these still fire — to fully pause, disable `Enabled`)
- HVAC constraints (these still flow — HVAC offsets and shed/coast/precool/preheat signals continue)

If you want **everything** paused, set the master `Enabled` switch to OFF.

---

## 9. Reading the activity log

`/config/universal_room_automation/data/universal_room_automation.db` table `ura_activity_log` records significant EC decisions. Filter by `coordinator='energy'`:

```sql
SELECT
  timestamp, action, importance, description, details_json
FROM ura_activity_log
WHERE coordinator = 'energy'
  AND timestamp > datetime('now', '-1 day')
ORDER BY id DESC;
```

Common action types:
- `arbitrage_phase_transition` — WAIT→CHARGE→HOLD→DISCHARGE transitions
- `arbitrage_gate_open` / `arbitrage_gate_closed` — gate state changes
- `arbitrage_chunk_completed` — per-chunk lock fired
- `arbitrage_forecast_recheck` — forecast re-classified on first WAIT→CHARGE
- `ev_paused_by_arbitrage` / `ev_resumed` — mutual-exclusion events
- `storage_mode_change` / `reserve_soc_change` / `charge_from_grid_change` — direct Enphase commands
- `load_shedding_engaged` / `load_shedding_cleared`
- `excess_solar_routed` — surplus diversion events
- `tou_transition` — off_peak ↔ mid_peak ↔ peak boundaries

`details_json` contains decision context (SOC, forecast values, calculated savings) for each event.

---

## 10. Architecture sketch (decision flow per cycle)

Every 5 minutes, the Energy Coordinator does, in order:

1. **Snapshot inputs** — pull current SOC, net power, solar, all six lifetime sensors, Solcast (today + tomorrow + D+2 if configured), Envoy availability, TOU period + rate.
2. **Day-rollover check** — if new date, reset daily counters, recalculate solar percentile thresholds, refresh predicted-bill counterfactual baseline.
3. **Strict precedence** — evaluate the five precedence rules from §3 in order.
4. **Battery strategy** — if precedence selects "off-peak arbitrage", determine WAIT / CHARGE / HOLD via gate + per-chunk lock + forecast re-check. Otherwise apply drain-target fallback.
5. **EV mutex** — if battery phase is CHARGE, pause EVSEs into `_paused_by_arbitrage`. Otherwise release (subject to other pause reasons).
6. **HVAC constraint** — compute current offsets (coast / precool / shed) and dispatch `energy_constraint_mode` to HVAC.
7. **Load shedding** — check grid import vs threshold over sustained window; fire signal if exceeded.
8. **Excess solar routing** — if SOC > threshold AND daily kWh budget allows, route surplus to configured destinations.
9. **Update sensors** — write fresh values to every dashboard sensor.
10. **Persist decision** — append to `ura_activity_log` if significant; update `arbitrage_cycles` if a charge cycle started/completed.

Each step is idempotent. Running it twice produces the same state. Race-safe across HA restarts.

---

## 11. Architecture sketch (arbitrage / EV mutual-exclusion)

The compound-load case (20 kW battery charge + 7.4 kW EV + 5 kW house base = ~134A on main breaker) is the panel-stress scenario v4.5.0 D4 prevents.

```
                      arbitrage_phase
                            │
                ┌───────────┴────────────┐
                │                        │
              CHARGE                   not CHARGE (WAIT/HOLD/DISCHARGE)
                │                        │
                ▼                        ▼
   ┌──────────────────────┐    ┌────────────────────────┐
   │ For each EVSE:       │    │ For each EVSE:         │
   │   if running:        │    │   if in _paused_by_   │
   │     turn_off()       │    │     _arbitrage set:    │
   │     add to           │    │       check other      │
   │     _paused_by_arb   │    │       pause reasons    │
   │   if not running:    │    │       (grid_cap,       │
   │     proactively      │    │        battery_drain)  │
   │     claim slot       │    │       if none → resume │
   │     so plug-in       │    │       remove from set  │
   │     can't start      │    │                        │
   └──────────────────────┘    └────────────────────────┘
```

The `_paused_by_<reason>` set + precedence-rule pattern is the same architecture v4.7.x will copy onto appliance controllers (LG ThinQ, Rainbird).

---

## 12. Related entities (not on this device but relevant)

- **HVAC Coordinator** — reads `energy_constraint_mode` from EC. See `docs/user-manual/HVAC_COORDINATOR.md` for how HVAC responds to coast / shed / precool / preheat.
- **Notification Manager** — fires alerts for major EC events (storm forecast, prolonged Envoy unavailability, arbitrage savings milestones).
- **Span Panel integration** — provides per-circuit power sensors used by the Circuit Anomaly detector.
- **Solcast PV Forecast integration** — provides the day-ahead solar forecasts that drive day classification.
- **Enphase Envoy integration** — the actuation surface (storage_mode / reserve_soc / charge_from_grid switches).

---

## Appendix: full entity list (URA: Energy Coordinator device)

### Sensors (daily snapshots & strategy)
| Entity ID | Purpose |
|---|---|
| `sensor.ura_energy_coordinator_battery_strategy` | 4-phase state machine label (WAIT / CHARGE / HOLD / DISCHARGE / BACKUP) |
| `sensor.ura_energy_coordinator_solar_day_class` | Today + tomorrow forecast class |
| `sensor.ura_energy_coordinator_tou_period` | Current TOU period |
| `sensor.ura_energy_coordinator_tou_rate` | Current $/kWh |
| `sensor.ura_energy_coordinator_tou_season` | Current TOU season (summer / winter) |
| `sensor.ura_energy_coordinator_current_rate` | Rate used in latest cost calc |
| `sensor.ura_energy_coordinator_delivery_rate` | Delivery rate |
| `sensor.ura_energy_coordinator_situation` | High-level energy + occupancy state |
| `sensor.ura_energy_coordinator_hvac_constraint` | Constraint mode signal to HVAC |

### Sensors (today / cycle / forecast)
| Entity ID | Purpose |
|---|---|
| `sensor.ura_energy_coordinator_energy_import_today` | Today's grid import kWh |
| `sensor.ura_energy_coordinator_energy_export_today` | Today's grid export kWh |
| `sensor.ura_energy_coordinator_cost_today` | Today's $ cost |
| `sensor.ura_energy_coordinator_cost_cycle` | Billing cycle $ cost |
| `sensor.ura_energy_coordinator_predicted_bill` | Current month bill prediction |
| `sensor.ura_energy_coordinator_total_consumption` | All-time consumption |
| `sensor.ura_energy_coordinator_net_consumption` | All-time net (consumption − production) |
| `sensor.ura_energy_coordinator_forecast_today` | Solcast PV forecast today |
| `sensor.ura_energy_coordinator_forecasted_import` | Forecast grid import |
| `sensor.ura_energy_coordinator_forecasted_consumption` | Forecast load consumption |
| `sensor.ura_energy_coordinator_battery_full_time` | Estimated SOC=100% time |
| `sensor.ura_energy_coordinator_forecast_accuracy` | 30-day rolling forecast accuracy |

### Sensors (arbitrage savings)
| Entity ID | Purpose |
|---|---|
| `sensor.ura_energy_coordinator_arbitrage_savings_today` | Today's est. savings |
| `sensor.ura_energy_coordinator_arbitrage_savings_cycle` | Cycle est. savings |
| `sensor.ura_energy_coordinator_arbitrage_savings_total` | Cumulative savings |

### Sensors (EV / circuits / diagnostics)
| Entity ID | Purpose |
|---|---|
| `sensor.ura_energy_coordinator_ev_charging_status` | Per-EVSE state |
| `sensor.ura_energy_coordinator_ev_charge_rate_a` / `_b` | Live A/B charger output |
| `sensor.ura_energy_coordinator_circuit_anomaly` | Per-circuit z-score anomaly detector |
| `sensor.ura_energy_coordinator_battery_decision` | Last decision-cycle reason text |
| `sensor.ura_energy_coordinator_load_shedding` | Current shed level (0–3) + reason |
| `sensor.ura_energy_coordinator_envoy_status` | Enphase availability + last comm |
| `sensor.ura_energy_coordinator_pool_optimization` | Pool pump schedule status |
| `sensor.ura_energy_coordinator_generator_status` | Backup runtime + fuel estimate |
| `sensor.ura_energy_coordinator_mode` | Coord mode + full attributes dump |

### Switches
| Entity ID | Purpose |
|---|---|
| `switch.ura_energy_coordinator_enabled` | Master — actuation kill |
| `switch.ura_energy_coordinator_observation_mode` | Compute + record but don't actuate |
| `switch.ura_energy_coordinator_arbitrage` | Enable the attain fill + three-rung ladder |
| `switch.ura_energy_coordinator_ev_tou_management` | Strict EV TOU pause (carries `override_active_until_iso`) |
| `switch.ura_energy_coordinator_evse_solar_aware_charging` | Solar-surplus EVSE absorb (formerly `excess_solar_charging`) |
| `switch.ura_energy_coordinator_grid_import_cap` | Binary EVSE-only import cap |
| `switch.ura_energy_coordinator_load_shedding` | Four-tier reactive shed cascade |

### Buttons
| Entity ID | Purpose |
|---|---|
| `button.ura_energy_coordinator_evse_force_charge_30min` | 30-min admin override of TOU EV pause (§10) |

### Inclement-weather (v5.5.1)
| Entity ID | Purpose |
|---|---|
| `sensor.ura_inclement_state` | Dedicated inclement-weather hold state observability entity |

### Number sliders
| Entity ID | Default | Purpose |
|---|---|---|
| `number.ura_energy_coordinator_peak_buffer_target` | 80% | SOC target during CHARGE |
| `number.ura_energy_coordinator_arbitrage_charge_lead_time` | 360 min | Charge window opens this far before high-rate transition |
| `number.ura_energy_coordinator_off_peak_drain_excellent` | 10% | Drain target on excellent solar day |
| `number.ura_energy_coordinator_off_peak_drain_good` | 15% | Drain target on good solar day |
| `number.ura_energy_coordinator_off_peak_drain_moderate` | 20% | Drain target on moderate solar day |
| `number.ura_energy_coordinator_off_peak_drain_poor` | 30% | Drain target on poor solar day |
| `number.ura_energy_coordinator_ev_battery_drain_soc` | 50% | SOC below which EV won't draw from house battery |

---

---

## 10. Admin override: EVSE force-charge button (v4.7.x)

### Why a button, not a switch?
A switch is a one-finger swipe — too easy to hit accidentally and leave active. A button + notification + audit trail is the "deliberate action" pattern. The button represents an explicit, time-bounded admin decision.

### `button.ura_energy_coordinator_evse_force_charge_30min`
**Entity:** `button.ura_energy_coordinator_evse_force_charge_30min`
**Device:** URA: Energy Coordinator

**What it does when pressed:**
1. Opens a 30-minute force-charge window during which URA's TOU pause is bypassed for all EVSEs.
2. Fires an NM info notification: `"EV force-charge window opened until HH:MM. Mid-peak rates apply."` (suppressed if observation mode is active).
3. Logs the activation with the UTC expiry timestamp.

**Auto-expiry:** the window expires automatically after 30 minutes. On the next decision cycle after expiry, URA resumes enforcing strict TOU pause. No manual cancellation needed — just wait.

**Idempotent re-press:** pressing the button while an override is already active replaces the window (30 min from now), not adds to it. Prevents accidental stacking.

**Override visibility:** `switch.ura_energy_coordinator_ev_tou_management` gains an `override_active_until_iso` attribute that shows the current window's UTC expiry (or `null` when inactive). Check this from Developer Tools → States to confirm the override is active.

**No HA-side bypass:** enabling the EVSE switch directly in HA while TOU is mid_peak/peak is still defeated by URA within ≤5 min (D1 strict enforcement). The force-charge button is the only supported override path.

**When to use:** intentional mid-peak EV charging (guest visiting, departure imminent, grid event). Not for routine off-peak charging — that happens automatically.

---

## 11. Weather Provider Manager (v4.7.x Cycle A)

### Sensors

| Entity ID | Purpose |
|---|---|
| `sensor.ura_weather_active_provider` | Active weather entity_id, or `none` / `all_stale` |
| `sensor.ura_weather_apparent_forecast_high` | Today's apparent-temperature forecast high (°F) |
| `binary_sensor.ura_weather_divergence` | On when ≥2 providers disagree beyond threshold |

### Form fields

These fields live in the CM → Energy step, alongside the existing Primary weather picker.

| Field | CONF key | Default | Description |
|---|---|---|---|
| Primary weather provider | `CONF_ENERGY_WEATHER_ENTITY` | (user-configured) | Existing field — first-choice provider |
| Secondary weather provider | `CONF_ENERGY_WEATHER_FALLBACK_1` | (empty) | Failover if primary is stale/unavailable |
| Tertiary weather provider | `CONF_ENERGY_WEATHER_FALLBACK_2` | (empty) | Second-level failover |
| Weather staleness limit | `CONF_WEATHER_STALENESS_MAX_HOURS` | 6h | Provider state older than this is treated as stale |
| Divergence threshold | `CONF_WEATHER_DIVERGENCE_THRESHOLD_F` | 5°F | When ≥2 providers differ by this much, divergence sensor turns ON |

**Migration from single-provider config:** your existing `CONF_ENERGY_WEATHER_ENTITY` value is preserved as the Primary provider. No changes required. Adding Secondary/Tertiary is opt-in.

**Apparent temperature vs raw temperature:** the manager reads `apparent_temperature` (felt temperature accounting for humidity + wind) from each provider's `weather.get_forecasts` response. If a provider doesn't expose apparent temperature, it falls back to raw `temperature` with an `apparent_confidence = "fallback_raw"` flag visible on `sensor.ura_weather_apparent_forecast_high` attributes.

---

**See also:**
- `docs/user-manual/HVAC_COORDINATOR.md` — the climate side of the same brain
- `docs/readmes/README_v4.5.0.md` — the original battery-strategy redesign
- `docs/readmes/README_v5.3.8.md` / `README_v5.3.9.md` — attain fill phase + three-rung ladder
- `docs/readmes/README_v5.5.0.md` — inclement-weather battery hold
- `docs/readmes/README_v5.4.1.md` — load-shedding correctness fixes
- `docs/readmes/README_v5.3.1.md` — energy unit normalization + 4-tier attribution
- `docs/QUALITY_CONTEXT.md` — bug-class catalog that reviews check against
- `docs/ENERGY_MANAGEMENT_EXPLAINER.md §15` — Weather Provider Manager architecture detail
