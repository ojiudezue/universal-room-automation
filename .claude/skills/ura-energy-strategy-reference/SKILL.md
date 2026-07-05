---
name: ura-energy-strategy-reference
description: URA energy-strategy domain reference. Load before touching any energy_*.py file — battery reserve / arbitrage / attain / inclement / EVSE / load-shed / TOU / SPAN / Envoy — or answering "why did the battery do X". Covers TOU + Bug Class #51 day-boundary gating, the four-phase arbitrage state machine (WAIT/CHARGE/HOLD/DISCHARGE), the attain sub-machine, inclement-hold graduated depth, Bug Class #53 reserve-floor leaks (WAIT bypass closed in v5.5.3 via `_floor_reserve`; invariant + Tier-3 routing fact-home is `ura-energy-invariants-campaign`), EVSE solar-first, source-trust hierarchy (SmartHub > SPAN/Emporia > Envoy; battery SOC = Envoy). Triggers: TOU, peak, arbitrage, attain, reserve, partial_hold, inclement, NWS, EVSE, solar, SOC, Envoy, SPAN, load shed, peak_buffer.
---

# URA Energy Strategy Reference

Domain theory for the URA energy family. Verified against source **2026-07-02** at v5.7.2. Every file:line here was greppable at that snapshot — re-verify before restating. **#1-ranked hardest URA domain**; do not skim.

**When NOT to use this skill.** Use `homeassistant_coding` for generic HA patterns; `ha-dashboard` for Lovelace card edits; `deploy` for the release pipeline; `documenter` for post-cycle doc updates. Presence/HVAC/safety questions do **not** belong here.

**Ground truth rule.** If you catch yourself writing "the strategy usually…" without a file:line — stop and grep. A fabricated spec here can cost real money or brick the battery.

---

## 0. Scope map — files, sizes, roles

| File | LoC (2026-07-02) | Role |
|---|---:|---|
| `domain_coordinators/energy.py` | 5955 | `EnergyCoordinator` god module; owns Envoy read, dispatches signals, wires sub-modules |
| `domain_coordinators/energy_battery.py` | 3440 | `BatteryStrategy.determine_mode()` + arbitrage 4-phase + attain sub-machine + reserve-floor plumbing |
| `domain_coordinators/energy_pool.py` | 2278 | `PoolOptimizer` (VSF speed) + `EVChargerController` (TOU pause, excess solar, fill-priority, force-charge) |
| `domain_coordinators/energy_tou.py` | 399 | `TOURateEngine` — period resolution + `peak_ahead_before_offpeak` (Bug Class #51 fix) |
| `domain_coordinators/energy_const.py` | 976 | `PEC_TOU_RATES`, drain-target defaults, arbitrage/attain constants, load-shed priority |
| `domain_coordinators/energy_forecast.py` | 789 | `DailyEnergyPredictor`, `AccuracyTracker`, `RoomPowerProfile` |
| `domain_coordinators/energy_billing.py` | 431 | `CostTracker`, `_get_effective_rate_kwh` |
| `domain_coordinators/energy_circuits.py` | 353 | `SPANCircuitMonitor`, `GeneratorMonitor`, `CircuitInfo` |
| `domain_coordinators/inclement.py` | ~750 | `AlertClassifier`, `SolarHorizon`, hold-depth decision (NWS alert + condition fusion) |
| `docs/ENERGY_MANAGEMENT_EXPLAINER.md` | 561 | Human-readable spec — canonical for tables/rates |
| `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` | 453 | Design of record |
| `docs/QUALITY_CONTEXT.md` | (Bug Classes) | #51 day-boundary-blind TOU; #53 computed-not-consumed control value |

---

## 1. TOU rate structure (verified `energy_const.py:15`, `docs/ENERGY_MANAGEMENT_EXPLAINER.md:80`)

**Utility:** PEC 2026 TOU Interconnect Metering (<50 kW). `PEC_TOU_RATES` is the built-in fallback; runtime loads `/config/universal_room_automation/tou_rates.json` if present via `TOURateEngine.async_from_json_file()` (`energy_tou.py:72`).

Import = export rate at every period (symmetric). Effective import rate adds delivery `$0.0225/kWh` + transmission `$0.0199/kWh` (`PEC_FIXED_CHARGES` @ `energy_const.py:68`) plus service availability `$32.50/mo`.

### Summer (Jun–Sep, months `[6,7,8,9]`)
| Period | Hours (24h) | Rate ($/kWh) |
|---|---|---:|
| off_peak | 00–14, 21–24 | 0.0435 |
| mid_peak (pre) | 14–16 | 0.0932 |
| **peak** | **16–20** | **0.1618** |
| mid_peak (post) | 20–21 | 0.0932 |

Summer is **bracketed**: mid_peak occurs BOTH sides of peak. This is the shape that spawned Bug Class #51 (see §2).

### Shoulder (Mar–May, Oct–Nov, months `[3,4,5,10,11]`)
| Period | Hours | Rate |
|---|---|---:|
| off_peak | 00–17, 21–24 | 0.0435 |
| mid_peak | 17–21 | 0.0864 |

**No peak** — mid_peak IS the highest-rate window.

### Winter (Dec–Feb, months `[12,1,2]`)
| Period | Hours | Rate |
|---|---|---:|
| off_peak | 00–05, 09–17, 21–24 | 0.0435 |
| mid_peak | 05–09, 17–21 | 0.0864 |

**No peak.** Two mid_peak brackets separated by a mid-day off_peak.

### Season / period resolution
- `TOURateEngine.get_current_season()` (`energy_tou.py:156`) matches month → season.
- `get_current_period(now)` (`energy_tou.py:165`) walks the hours-list for the season; defaults to `off_peak` on no match (`:176`).
- `peak_ahead_before_offpeak(now)` (`energy_tou.py:247`) — forward walker, midnight+season-boundary safe by construction (re-derives period every step). Do not replace with an "index today's table" scan.
- `get_next_high_rate_transition()` (`energy_tou.py:323`) — wrap-around aware "when do we next leave off_peak?".

---

## 2. Bug Class #51 — Day-Boundary-Blind TOU Decision (canonical example, do not repeat)

**Filed** 2026-06-07 at `docs/QUALITY_CONTEXT.md:2045`.

**Shape.** Any branch of the form `if period == "mid_peak": hold_for_peak()` — "mid_peak" alone doesn't tell you whether the peak is ahead or behind you. In summer, mid_peak (20–21) HELD the battery "for the upcoming peak" when peak was over and off_peak was 1 hour away — burned expensive kWh for nothing.

**Fix pattern.**
1. Use `peak_ahead_before_offpeak(now)` on `TOURateEngine`. It walks `now → now+24h`, returns True on any `peak` hour it encounters, False on the first `off_peak`.
2. Currently called at:
   - `energy_battery.py:2320` — mid_peak hold gate
   - `energy_battery.py:2963`, `:2992` — attain adoption + arbitrage entry
3. **Test PRE and POST bracket cases separately.** A single "during mid_peak" test fires the same branch as production and cannot see the bug.

**Detection grep.**
```
grep -nE 'period.*==\s*"(mid_peak|peak)"|current_period\s*in.*\("(peak|mid_peak)' \
  custom_components/universal_room_automation/domain_coordinators/energy*.py
```
Every hit that does **not** call `peak_ahead_before_offpeak` (or `get_next_high_rate_transition`) is a candidate #51.

---

## 3. Battery decision priority chain (verified `docs/ENERGY_MANAGEMENT_EXPLAINER.md:114`, `BatteryStrategy.determine_mode` in `energy_battery.py`)

Evaluated **top-down every 5 min** (default decision cycle). First match wins:

| # | Condition | Action |
|---|---|---|
| 1 | Envoy unavailable | Hold current state, issue no commands |
| 2 | Grid disconnected | Switch to `backup` storage mode |
| 3 | Storm / inclement WARN | Pre-charge to 90% via `charge_from_grid`, then `full_hold` in `self_consumption` |
| 4 | Inclement WATCH corroborated OR condition-only ≥2 providers | `partial_hold` or `full_hold` per graduated depth (§5) |
| 5 | Peak period | Discharge (reserve = configured minimum, default 20%) |
| 6 | Mid_peak + `peak_ahead_before_offpeak(now)` | Hold (reserve = current SOC) |
| 7 | Mid_peak + NO peak ahead | Discharge (Bug Class #51 fix) |
| 8 | Off_peak + arbitrage enabled + gate open | Arbitrage 4-phase state machine (§4) |
| 9 | Off_peak fallback | SOC-conditional drain vs. drain_target (§3.1) |

### 3.1 Off-peak drain targets (Solcast-conditional)

From `DEFAULT_OFFPEAK_DRAIN_*` (`energy_const.py:33`). Applied as `reserve_level`. **`reserve_level` is a discharge FLOOR, not a charge ceiling** (module docstring `energy_battery.py:11`) — solar can still charge above it.

| Tomorrow's solar class | Drain target (SOC %) | Rationale |
|---|---:|---|
| excellent (≥P75) | 10 | Solar refills; maximize absorption headroom |
| good (≥P50) | 15 | Solar refills |
| moderate (≥P25) | 20 | Off_peak grid $0.0435 is ~3.7× cheaper than peak |
| poor (<P25) | 30 | Arbitrage may catch worst case |
| very_poor | poor fallback | Same |
| unknown | 40 | Conservative default |

If SOC > drain target → discharge stored solar; if SOC ≤ drain target → hold (import cheap grid).

---

## 4. Arbitrage 4-phase state machine (verified `energy_battery.py:7–95`, `:1003–1560`)

**Module docstring** (`energy_battery.py:7`):
> Off-peak is a four-phase state machine when arbitrage is enabled:
> `WAIT → CHARGE → HOLD → DISCHARGE`

Phase constants (`energy_battery.py:56`):
- `ARBITRAGE_PHASE_WAIT = "wait"`
- `ARBITRAGE_PHASE_CHARGE = "charge"`
- `ARBITRAGE_PHASE_HOLD = "hold"`
- `ARBITRAGE_PHASE_ATTAIN = "attain"` — sub-state (§4.3)
- `ARBITRAGE_PHASE_NA = "n/a"` — outside off_peak / gate not fired

### 4.1 Phase → action matrix (`_get_arbitrage_decision` docstring `energy_battery.py:1541`)

| Phase | `reserve_level` | `charge_from_grid` | Notes |
|---|---|---|---|
| WAIT | `self.reserve_soc` | OFF | Waiting for window open OR gate re-eval. **Known #53 leak — §6.** |
| CHARGE | `peak_buffer_target` (default 80) | **ON** | Grid-charging chunk |
| HOLD | `peak_buffer_target` | OFF | Chunk hit target; hold until high-rate boundary |
| ATTAIN | dynamic (solar-informed) | ON while charging | Mid-off_peak peak-buffer catch-up (§4.3) |
| DISCHARGE (legacy) | drain target | OFF | Arbitrage off / gate closed → fall through to §3.1 |

**Chunk semantics.** A "chunk" = one WAIT→CHARGE→HOLD sequence. `_arbitrage_chunk_completed=True` when CHARGE first hits `peak_buffer_target`; later ticks HOLD without re-firing CHARGE (`energy_battery.py:1558`).

### 4.2 Arbitrage gate pre-conditions (`_arbitrage_pre_conditions` @ `energy_battery.py:1360`)

ALL required to consider any arbitrage phase:
- `arbitrage_enabled=True` (from `switch.ura_energy_coordinator_grid_arbitrage`)
- Tomorrow's solar class ∈ {`poor`, `very_poor`} (D+2 optional if multi-day horizon on)
- Window open: `(next_high_rate_transition - now) ≤ arbitrage_charge_lead_time_min` (default 360 min = 6 h; range 120–720)
- Rung-0 solar-attainability gate passes (§4.4)

### 4.3 Attain sub-state — peak-buffer catch-up (verified `energy_battery.py:61–95, 325–360, 2963`)

**When.** SOC is BELOW `peak_buffer_target` inside a charge window (off_peak, or mid_peak where mid_peak rate < peak rate AND `peak_ahead_before_offpeak(now)`). Attain kicks in.

**Constants (`energy_battery.py:74–95`):**
- `ATTAIN_RATE_WINDOW_TICKS = 3` — smooth observed net charge rate over 15 min (3 × 5-min ticks).
- `SOLAR_CAPTURE_FACTOR = 0.5` — fraction of Solcast remaining-day kWh we expect to capture into battery before boundary. Unavailable/stale Solcast → treat surplus as 0 (fail toward charging).
- `ATTAIN_MIN_REMAINING_MIN = 30` — minimum minutes-to-boundary to ENTER attain (Enphase cloud actuation lag ~35 min). Latched attain CONTINUES below this; only ENTRY is gated.
- `ATTAIN_PEAK_HANDOFF_LEAD_MIN = 15` — minutes before a PEAK boundary that a latched attain commands turn-off/handoff.

**Tri-state (`energy_battery.py:334`):** `_attain_state ∈ {"inactive", "charging", "holding"}`.

**Reboot recovery (`energy_battery.py:2310–…`, "Cycle EC/HC reboot pickup").**
- SOC ≥ target with a boundary ahead → adopt `holding`.
- SOC < target inside an active charge window → adopt `charging`.
- Hardware state, not RestoreEntity, is the source of truth.

**Constraint.** `attain` MUST NOT pause EVSEs (`energy_battery.py:65` comment). Only CHARGE pauses EVSEs via the `arbitrage_charging` gate in `energy.py`.

### 4.4 Solar-attainability ladder (v5.5.0+, `_classify_attain_rung` @ `energy_battery.py:1122`)

3-rung classifier setting `_arbitrage_intent`:

| Rung | Condition | Gate | `_arbitrage_intent` |
|---|---|---|---|
| rung_0 | Solar projection ≥ target + 3% hysteresis | **CLOSED** (solar will handle) | `None` |
| rung_1 | Solar can hit target IF EVs paused | **CLOSED**; EVs paused to redirect | `"redirect"` |
| rung_2 | Neither passes | Existing arbitrage CHARGE fires | `"breaker"` |

- Symmetric 3% / 3% hysteresis (`ARB_LADDER_ENTRY_HYSTERESIS_PCT`, `ARB_LADDER_EXIT_HYSTERESIS_PCT` @ `:105`) — 6-pt dead-band absorbs Solcast tick wobble.
- `ARB_LADDER_SOLAR_NEGLIGIBLE_PCT_PER_H = 0.5` — below this expected surplus, rung-1 is meaningless (night/deep-overcast); short-circuit to rung_2.
- Latches `_arb_rung0_latch` / `_arb_rung1_latch` are RAM-only (`:375`).

### 4.5 Defensive grid-import guard (`_grid_import_guard_exceeded`, v4.5.0.2)

If actual grid import exceeds `arbitrage_grid_import_guard_kw` for `_arbitrage_guard_consecutive_trips` ticks during CHARGE → abort chunk (return WAIT). Protects undersized breakers when house + EV + arbitrage stack. Disabled by default (`_arbitrage_grid_import_guard_enabled`); dormant opt-in (`energy_const.py:528` context).

---

## 5. Inclement-weather hold — graduated depth (verified `inclement.py:53, 152, 293, 510–705`; `energy_battery.py:739–1000`)

Replaced the legacy Storm Guard's blunt 100% grid pre-charge with an **NWS alert + condition fusion** producing three hold depths.

**Hold-depth type** (`inclement.py:53`): `Literal["full_hold", "partial_hold", "allow_discharge"]`.

### 5.1 Tier ladder (from CAP alert classifier)

`AlertClassification.tier ∈ {"warn", "watch", "notice", "none"}` (`inclement.py:52, 62`).

`AlertClassifier.classify()` (`inclement.py:170`) walks each active alert:
- `Status` must be actual/actionable (`_ACTIONABLE_STATUSES`).
- `Ends`/`Expires`: drop expired via `_alert_expires_at()` (`:129`).
- `Certainty` ∈ observed/likely → tier candidate; else → `watch`-candidate.
- Event ending in "warning" → tier bumps.
- `Severity` gated against `warn_min_severity` (severity < config → demoted warn → watch).
- `_max_tier` across alerts wins.

### 5.2 Hold-depth decision (`_hold_depth_decision`-family, `inclement.py:551–705`)

| Tier | Corroboration | Solar horizon recoverable? | Decision | reserve_floor |
|---|---|---|---|---|
| none | — | — | `allow_discharge` | — |
| notice | — | — | `allow_discharge` (`tier_notice_allow_discharge`) | — |
| watch | uncorroborated + off_peak | — | `partial_hold` | `partial_hold_reserve_floor` |
| watch | uncorroborated + mid/peak | — | `allow_discharge` | — |
| watch | corroborated + off_peak | — | `full_hold` | `_full_hold_floor(current_soc)` |
| watch | corroborated + not off_peak | recoverable | `partial_hold` | `partial_hold_reserve_floor` |
| watch | corroborated + not off_peak | NOT recoverable | `full_hold` | `_full_hold_floor(current_soc)` |
| warn | any | — | `full_hold` | `_full_hold_floor(current_soc)` |
| — (no alert) | ≥2 healthy providers stormy + off_peak | — | `partial_hold` (`condition_only_offpeak_partial_hold`) | `partial_hold_reserve_floor` |
| — | ≥2 providers stormy + not off_peak | — | `allow_discharge` | — |

- `CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR` / `DEFAULT_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR` at `energy_battery.py:753,760`. Default = 50 (memory line).
- `_full_hold_floor(current_soc)` → freeze at present charge.
- **Solar horizon** = time until alert expiry vs. expected solar recovery classes (`SolarHorizon` @ `inclement.py:293`, `compute_solar_horizon` @ `:326`).

### 5.3 D0 wiring caution (memory `project_v5_5_0_inclement_weather_shipped`, 2026-06-15)

**Inclement feature is dormant until NWS entity is wired.** The `nws_alerts_entity` config must be set to a valid HA NWS entity; else the classifier only sees `None` and returns tier=`none`. Verify:
```
ha_get_state({"entity_id":"sensor.ura_energy_coordinator_battery_strategy"})
# → attributes.inclement_hold_depth should not be "n/a" when an alert is active
```

---

## 6. Bug Class #53 — Computed-but-not-consumed reserve floor

**Filed** at `docs/QUALITY_CONTEXT.md:2168`. Shape: a decision function computes a floor / clamp value, threads it into SOME return branches, silently drops it in others, but STILL exposes the value as an attribute — the attribute lies about a protection the code doesn't actually enforce.

**Guard helper.** `BatteryStrategy._floor_reserve(existing, effective_reserve, hold_depth)` at `energy_battery.py:1519`. Byte-identical to `existing` unless `hold_depth == "partial_hold"` AND `effective_reserve is not None` AND `effective_reserve > existing`; uses `max()` so it can only RAISE. **All reserve emission sites MUST route through this helper.**

**Fact-home for the full clamp-site table (7 call sites: WAIT :1617 v5.5.3-fixed, HOLD :1568, CHARGE :1591, plus :2115/:2169/:2400/:3000) and the Tier-3 routing rationale for any change touching `_floor_reserve` or its emission set: `ura-energy-invariants-campaign` §Phase 1–2.** The pre-v5.5.3 anchor `energy_battery.py:1521` is historical — do not present as current. The originally-cited arbitrage-WAIT floor bypass was closed in v5.5.3; any new session must re-verify against current source before treating it as open.

---

## 7. EVSE controller — solar-first EV philosophy (verified `energy_pool.py:163–663`)

**Operator-durable principle** (memory `project_ev_pause_post_peak_midpeak_decision`):
> solar-first → never drain battery into car → off_peak grid cheapest

Implementation: `EVChargerController` (`energy_pool.py:181`). Default EVSEs: `switch.garage_a`, `switch.garage_b` (`DEFAULT_EVSE_ENTITIES` @ `:163`).

### 7.1 Pause-reason bookkeeping — independent owner sets (verified `:200–276`)

Independent owner sets. **Sharing sets = collision-by-set-overload (Bug Class #46, load-shed audit). Each owner MUST have its own set.**

| Owner set | Reason | Enable via |
|---|---|---|
| `_paused_by_us` | TOU peak/mid_peak strict pause | `switch.ura_energy_coordinator_ev_tou_management` (default ON) |
| `_paused_by_grid_cap` | Grid-import cap exceeded | `switch.ura_energy_coordinator_grid_import_cap` |
| `_paused_by_arbitrage` | Compound-load guard during arbitrage CHARGE (v4.5.0 D4) | Arbitrage state machine |
| `_paused_by_fill_priority` | SOC < `fill_priority_soc` + solar OK (v4.7.6 D2) | `switch.ura_energy_coordinator_excess_solar_charging` gate |
| `_paused_by_load_shed` | Reactive peak limiter | `switch.ura_energy_coordinator_load_shedding` (**DORMANT — §9**) |
| `_excess_solar_active` | Actively force-charging with surplus solar | `switch.ura_energy_coordinator_excess_solar_charging` |

**Force-charge override.** `EVSEForceChargeButton` opens `_force_charge_until` (`energy_pool.py:238`, default 30 min). While active, ALL pause sets are bypassed and an NM notification fires. Never settable from HA UI directly (`:237`).

### 7.2 TOU pause is STRICT + idempotent (v4.7.x)

`docs/ENERGY_MANAGEMENT_EXPLAINER.md:170` — every decision cycle during peak/mid_peak issues `switch.turn_off` regardless of prior `_paused_by_us` state. Prior bookkeeping-short-circuit let manual re-enables silently defeat policy. Now: ≤5 min catchup after any manual override.

### 7.3 Excess solar + fill-priority — gate order matters

Excess-solar activation (`determine_excess_solar_actions` @ `:692`):
- Battery SOC ≥ `energy_excess_solar_soc` (default 95%)
- Solcast remaining forecast ≥ `energy_excess_solar_kwh` (default 5.0 kWh)

Fill-priority (`_fill_priority_soc` @ `energy.py:307`, default from `CONF_ENERGY_FILL_PRIORITY_SOC`): while SOC < threshold AND solar forecast healthy, pause EVSEs so battery fills first. First-pause-per-day fires NM notification (`_fill_priority_nm_trip_date` @ `energy.py:317`).

### 7.4 EV off-peak ensure-on + persistence (v4.7.28, LIVE)

During off_peak, if arbitrage/load-shed/fill-priority all clear, the EVSE is force-turned-on (ensure-on) + claimed for arbitrage-hardware bookkeeping. Prevents "silent EV off" (`energy_pool.py:471,502,563`). Restart-persistent.

---

## 8. Battery ↔ EV hold interaction

**Problem.** EVSE draw looks like house load to Envoy → battery discharges to cover 11.5 kW → stored solar wastes covering grid-priced load.

**Solution.** `_evse_battery_hold_active` — when any EVSE `power > EVSE_CHARGING_POWER_THRESHOLD` (100 W, `energy_pool.py:305, 323`), battery `reserve_level` overrides to current SOC. Battery holds; EV pulls from grid at cheap off_peak rate. Released when charging stops.

Verify live:
```
ha_get_state({"entity_id":"sensor.ura_energy_coordinator_battery_strategy"})
# attributes: evse_battery_hold_active + arbitrage_phase
```

---

## 9. Load shedding — DORMANT / do not enable

Cascade priority (`energy_const.py:632`):
```
LOAD_SHEDDING_PRIORITY = ["pool", "ev", "smart_plugs", "hvac"]
```

Levels 1–4 tracked in `EnergyCoordinator._load_shedding_active_level` (`energy.py:424`).

Pool sub-tiers (`energy_pool.py:56`):
- **Tier 1.** Reduce VSF speed during peak (75→30 GPM, ~94% power savings via affinity law). LIVE.
- **Tier 2.** Shed infinity edge during peak (STUBBED, off by default).
- **Tier 3.** Full shutdown (STUBBED, off by default).

**Status: DORMANT + unsafe.** Memory `project_load_shedding_audit_backlog`:
- Audit 2026-06-08 found 1 CRITICAL (EV tier previously shared `_paused_by_us` with EVSE TOU control — now split into `_paused_by_load_shed`, but the tier is dead + unsafe to test), 2 HIGH (orphan restore, manual-off clobber).
- Operator directive 2026-06-12 (memory `project_load_shedding_ip_capability_hold`): **"not a normal cycle"** — treat as IP-grade capability; vision/architecture doc required before any build.

**Do not.**
- Set `switch.ura_energy_coordinator_load_shedding` = on outside a controlled bench harness.
- Add code to the EV load-shed tier without threading its own owner set — a shared set with TOU pause was the original CRIT.
- Merge load-shed work into a Tier 1 or Tier 2 feature cycle. Dedicated Tier 2-DB (or Tier 3).

Reactive peak-limiter fields exist and are wired (`energy.py:395–424` — `_load_shedding_threshold_kw`, `_load_shedding_sustained_minutes`, `_load_shedding_mode` ∈ {`fixed`, `auto`}) but stay behind the master switch.

---

## 10. Energy-source trust hierarchy — canonical

**Operator-durable directive** (memory `project_battery_soc_envoy_not_span`, 2026-06-16):
> Battery SOC = Envoy, NOT SPAN. SPAN `battery_level` miscalibrated (read 97.6% vs. Envoy fleet 71%).

### Rank order

| Rank | Signal | Source | Notes |
|---|---|---|---|
| 1 | Grid utility import billing | SmartHub (utility portal) | Ground truth for cost reconciliation; not real-time |
| 2 | Per-circuit power | SPAN (per-breaker CT) + Emporia (EVSE mains) | Real-time; use for circuit attribution |
| 2 | Grid net power | Emporia mains sensor (optional direct) | `energy.py:339` — optional direct grid import/export |
| 3 | Battery SOC | **Envoy** (`sensor.envoy_*_battery`) | Canonical. Wired via `CONF_ENERGY_BATTERY_SOC_ENTITY` (`energy.py:365`) |
| 3 | Solar production, net grid, battery capacity | Envoy | `current_net_power_consumption`, `battery_capacity`, etc. |
| 3 | Reserve number | Enpower (`number.enpower_*_reserve_battery_level`) | The lever we write to |

### Verify live SOC source (do NOT infer from friendly names)

```
ha_get_state({"entity_id":"sensor.envoy_482543015950_battery"})   # Envoy — authoritative
ha_get_state({"entity_id":"sensor.span_panel_battery_level"})     # SPAN — DO NOT USE for control
```

**Known Enphase-side quirk (unverified):** reserve reporting divergence between Enpower `number` (80) and Envoy-reported reserve (20) at moment of the memo. Enphase cloud state, not URA.

### Envoy degradation handling

- `_envoy_degraded` (`energy.py:560`) — True this cycle when critical envoy entities missing/unavailable. Set boot-timestamp `_envoy_degraded_since` (`:561`).
- `_envoy_data_anomaly_at` (`:565`) — envoy status "online" but data zeroed/wrong.
- `_envoy_unavailable_count` (`:552`) — reset on availability; log at each recovery.
- Restart-persistence via envoy cache: `_save_envoy_cache` @ `energy.py:1353`, `_restore_envoy_cache` @ `:1384`.
- Live-validation tag surfaced as `sensor.ura_energy_envoy_status`.

**Boot incident 2026-06-12** (memory `project_envoy_boot_incident_2026_06_12`): after_dependencies stranding + one-shot EC validation race + RestoreEntity `unavailable→OFF` poisoning. Do not rely on `last_state.state == "on"` without an `unavailable`/`unknown` guard — that is Bug Class #52.

---

## 11. Billing / forecast / circuits — brief

### Billing (`energy_billing.py`, 431 LoC)
- `CostTracker` (`:91`) accumulates cost via `_get_effective_rate_kwh()` (`:28`) that adds delivery + transmission to base TOU rate. Symmetric export credit.

### Forecast (`energy_forecast.py`, 789 LoC)
- `DailyEnergyPredictor` (`:38`) — daily consumption forecast.
- `AccuracyTracker` (`:500`) — measured vs. predicted.
- `RoomPowerProfile` (`:635`) — per-room consumption fingerprint for room-attribution.
- `get_time_bin(hour)` (`:627`) — bin index used by profile + predictor.

### Circuits (`energy_circuits.py`, 353 LoC)
- `SPANCircuitMonitor` (`:59`) — per-breaker consumption; autodiscover via `CONF_ENERGY_CIRCUIT_AUTODISCOVER_SPAN` (`energy.py:324`).
- `GeneratorMonitor` (`:302`) — generator run detection.
- `CircuitInfo` (`:43`) — per-circuit metadata dataclass.

**Warning** (memory `hygiene_bucket_yaml_span`) — 18 SPAN circuits were renamed; baselines need re-mapping. Config hygiene, not URA-core.

---

## 12. Signal surface — what the sensor.py entity exposes

Sensor: `sensor.ura_energy_coordinator_battery_strategy` (unique_id `<domain>_battery_strategy` @ `sensor.py:6766`).

Attributes to spot-check during any strategy change (see `sensor.py:7019–7025`):

| Attribute | Values | Meaning |
|---|---|---|
| `arbitrage_phase` | `wait | charge | hold | attain | n/a` | Which arm of §4 fired |
| `arbitrage_intent` | `redirect | breaker | None` | Solar-ladder rung outcome |
| `attain_state` | `inactive | charging | holding` | Sub-machine |
| `attain_projected_soc`, `attain_solar_term_pct` | float | Frozen at entry when latched |
| `inclement_hold_depth` | `full_hold | partial_hold | allow_discharge | n/a` | §5 outcome |
| `inclement_reserve_floor` | int / null | Floor the strategy CLAIMS to honor — cross-check §6 |
| `evse_battery_hold_active` | bool | §8 |

Dispatched signals (`domain_coordinators/signals.py`):
- `SIGNAL_ENERGY_CONSTRAINT = "ura_energy_constraint"` (`:13`)
- `SIGNAL_ENERGY_ENTITIES_UPDATE = "ura_energy_entities_update"` (`:22`)
- `SIGNAL_ENERGY_COORDINATOR_READY = "ura_energy_coordinator_ready"` (`:72`)

---

## 13. Change-safety checklist before touching energy code

Tick each before editing `energy_*.py` / `inclement.py`.

- [ ] Read `docs/ENERGY_MANAGEMENT_EXPLAINER.md` §5–6 (strategy contract) + `docs/Coordinator/ENERGY_COORDINATOR_DESIGN_v2.3.md` §1 (design philosophy).
- [ ] Grep every `"reserve_level"` return site in `energy_battery.py`. Each must route through `_floor_reserve` OR be provably unreachable for `(partial_hold, non-None floor)`. (**Bug Class #53**)
- [ ] Grep every `period == "mid_peak"` and `period == "peak"` branch. Each must call `peak_ahead_before_offpeak` or `get_next_high_rate_transition`. (**Bug Class #51**)
- [ ] If touching EVSE pause: confirm each owner has its own `_paused_by_*` set. Do NOT merge sets. (**Bug Class #46 exemplar**)
- [ ] If touching load shed: STOP. Route to a dedicated Tier 2-DB (or Tier 3) cycle. (§9)
- [ ] If touching SOC read: confirm you're reading Envoy, not SPAN. (§10)
- [ ] If touching arbitrage / attain / inclement: this is regression-prone → apply Tier 2-DB (three framing-disjoint reviews per project CLAUDE.md) even without a DB migration.
- [ ] If threading a new reserve-floor / clamp / gate value: state the falsifiable invariant in the planning doc; run Tier 3's adversarial-completeness pass D on the diff. (v5.5.3 D-HIGH-1 lesson.)
- [ ] Post-deploy: write live-validation results into `docs/readmes/README_v<version>.md` (README write-back is mandatory).

### Doing tiered reviews yourself (no subagent fleet)

Per project CLAUDE.md the standing policy is "3 framing-disjoint reviews for regression-prone work." If you don't have a subagent fleet, do them SEQUENTIALLY against yourself with explicitly disjoint framings and hard-restated framing statements. Do NOT collapse them into one pass; blind spots converge.

- Review A — **local correctness**. Arithmetic, clamp helpers, per-site logic. State the invariant.
- Review B — **integration / state-machine integrity**. No regression on unchanged paths; byte-identical on the no-op path; restart resilience.
- Review C — **test authority**. Real per-site source mutation (bypass ONE load-bearing site at a time, confirm a SPECIFIC test fails, restore). Aggregate monkeypatch is not sufficient (v5.3.8 attain lesson).
- Optional Review D (Tier 3) — **adversarial completeness / diff-blind**. Re-enumerate the ENTIRE invariant surface including pre-existing code; break the invariant with a concrete legal-config repro. v5.5.3 D-HIGH-1 was pre-existing, missed by A/B/C.

An optional subagent fleet (`ura-reviewer` etc.) speeds this up but is NOT the source of the guarantee. The guarantee is the framings + the mutation-anchored test.

---

## 14. Fast triage — "the battery did something weird"

Run in order. Stop at first hit.

1. **Envoy alive?**
   ```
   ha_get_state({"entity_id":"sensor.envoy_482543015950_battery"})
   ```
   If unavailable → priority-1 fires; strategy holds. Not a bug.
2. **SOC source?** Envoy value ≠ SPAN? Expected — trust Envoy (§10). If code is reading SPAN, that's the bug.
3. **What phase does the sensor say?**
   ```
   ha_get_state({"entity_id":"sensor.ura_energy_coordinator_battery_strategy"})
   ```
   Look at `arbitrage_phase`, `attain_state`, `inclement_hold_depth`, `inclement_reserve_floor`, `evse_battery_hold_active`.
4. **Inclement dormant?** `inclement_hold_depth == "n/a"` with an active NWS alert → NWS entity is unwired (§5.3).
5. **Mid_peak hold looks wrong?** Confirm `peak_ahead_before_offpeak(now)` returned True. Summer post-peak mid_peak (20–21) is the classic #51 site.
6. **Reserve attr disagrees with hardware behavior?** Bug Class #53 (§6). Re-run the clamp-site enumeration per `ura-energy-invariants-campaign` §Phase 1 — the WAIT bypass was closed in v5.5.3 but a new emission site can re-open the class.
7. **EV kept charging during peak?** Check `_force_charge_until` (button pressed), then Grid Import Cap coexistence (`_paused_by_grid_cap` independent of `_paused_by_us`).
8. **Logs.**
   ```
   ha_get_logs({"filter":"universal_room_automation.domain_coordinators.energy"})
   ```
9. **Direct DB.** MCP `ura-sqlite` — verify `~/.claude.json` `--db-path` points at the live Samba-mounted path (fact-home: `ura-diagnostics-and-tooling`), NOT `~/.cache/ura/`.

**If the Samba mount or MCP is down**, fall back to SSH into HA (`ssh homeassistant@192.168.13.13`) and read `/config/universal_room_automation/data/universal_room_automation.db` directly with `sqlite3`. Same DB, direct FS.

---

## 15. Provenance and maintenance

**Verified 2026-07-02 at URA v5.7.2.** Re-verify any of the below before restating in another skill or planning doc:

```bash
# TOU rate table
grep -n 'PEC_TOU_RATES:' custom_components/universal_room_automation/domain_coordinators/energy_const.py

# Bug Class #51 helper + call sites
grep -n 'peak_ahead_before_offpeak' custom_components/universal_room_automation/domain_coordinators/energy_tou.py
grep -n 'peak_ahead_before_offpeak' custom_components/universal_room_automation/domain_coordinators/energy_battery.py

# Arbitrage 4-phase + attain constants
grep -n 'ARBITRAGE_PHASE_\|ATTAIN_\|SOLAR_CAPTURE_FACTOR' \
  custom_components/universal_room_automation/domain_coordinators/energy_battery.py

# Bug Class #53 guard helper + known-open WAIT site
grep -n '_floor_reserve\|"reserve_level"' \
  custom_components/universal_room_automation/domain_coordinators/energy_battery.py

# Inclement hold depth type + decision family
grep -n '_HoldDepth\|hold_depth=\|reserve_floor=' \
  custom_components/universal_room_automation/domain_coordinators/inclement.py

# EVSE owner sets
grep -n '_paused_by_' custom_components/universal_room_automation/domain_coordinators/energy_pool.py

# Load-shed priority (verify still dormant)
grep -n 'LOAD_SHEDDING_PRIORITY\|_load_shedding_enabled' \
  custom_components/universal_room_automation/domain_coordinators/energy_const.py \
  custom_components/universal_room_automation/domain_coordinators/energy.py

# Bug Classes 51 + 53 canonical text
sed -n '2045,2110p;2168,2200p' docs/QUALITY_CONTEXT.md
```

**Drift risks.**
- LoC counts (§0) — energy.py grows.
- Default numeric constants (drain targets, `DEFAULT_PEAK_BUFFER_TARGET = 80`, `DEFAULT_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR = 50`, `arbitrage_charge_lead_time_min` bounds 120–720). Re-grep `energy_const.py`.
- The exact line for the arbitrage-WAIT floor gap (`~1521` at v5.5.0; area shifts with fix-ups).
- Envoy device MAC in example commands (`482543015950` here) may not match your install — read entity registry.

**Related memory bodies** (project index in `.claude/memory/MEMORY.md`):
- `project_v5_5_0_inclement_weather_shipped` — inclement design + D0 NWS wiring caveat
- `project_inclement_arbitrage_wait_floor_gap` — the OPEN #53 site
- `project_battery_soc_envoy_not_span` — source-trust operator directive
- `project_ev_pause_post_peak_midpeak_decision` + `project_ev_offpeak_cycle_pickup` — EV philosophy + off-peak ensure-on
- `project_load_shedding_audit_backlog` + `project_load_shedding_ip_capability_hold` — DORMANT status
- `project_envoy_boot_incident_2026_06_12` — after_dependencies + RestoreEntity poisoning (Bug Class #52 adjacent)
- `project_optimizer_db_write_flood_incident_2026_06_09` — non-energy cause of energy-adjacent instability
