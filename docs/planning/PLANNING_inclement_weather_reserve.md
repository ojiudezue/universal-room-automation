# PLANNING — Robust Inclement-Weather Detection + TOU/Solar-Horizon-Aware Battery Hold

**Status:** **FINAL / BUILD-READY** (FIN-1 / FIN-2 / FIN-3 + EV/EVSE audit clean bill of health applied 2026-06-15). No further plan edits before build — any further changes are scope creep and require a new revision header.
**Branch:** `develop`
**Target version:** TBD (**Tier 2-DB** — modifies the `determine_mode` peak/mid_peak arbitrage discharge branches directly; cost-impacting AND backup-safety-impacting; cross-coordinator ripple risk).
**Goal:** Replace URA's reliance on Enphase Storm Guard (cloud-only, NWS-driven, no local veto, multi-day stale locks, blunt 100% grid pre-charge) with a local **alert + condition fusion** that produces a **graduated hold-depth decision** parameterized by (a) confidence tier, (b) current TOU period, and (c) solar recovery horizon — so warnings during off_peak with a sunny morning ahead are treated very differently from warnings at sunset heading into an overnight outage window.

Operator thesis (verbatim): *"These warnings mean sth entirely different during the morning with solar ahead vs at night with 6-12 hours of darkness and no solar recharge. And when off peak, mid peak and peak occur relative to the weather alert. We should probably guard midpeak and peak a bit unless confidence is high."*

---

## Institutional context verified

### Files read end-to-end / partial during scoping
- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — storm path, determine_mode precedence chain, peak / mid_peak / off_peak branches, extra_state_attributes, solcast accessors, **attainability helpers `_expected_solar_surplus_pct` (energy_battery.py:1362–~1430) and `_should_attain_peak_buffer` (energy_battery.py:1587–~1665) — re-verified end-to-end for FIN-2 reuse; the solar-surplus term subtracts the observed net-load implicitly (it's a fraction of forecast Solcast pro-rated by the OVERLAP window and scaled by `SOLAR_CAPTURE_FACTOR=0.5` to absorb non-battery house load + losses)**.
- `custom_components/universal_room_automation/domain_coordinators/energy_tou.py` — `peak_ahead_before_offpeak()`, `get_current_period()`, `get_next_transition()` — already provide the TOU-window arithmetic we need.
- `custom_components/universal_room_automation/domain_coordinators/weather_manager.py` — election / health / staleness / divergence.
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — re-export point for `CONF_/DEFAULT_` weather and solcast constants.
- `custom_components/universal_room_automation/config_flow.py` (existing weather entity-selector step ≈ lines 3220–3450).
- `custom_components/universal_room_automation/__init__.py` (weather entity propagation ≈ lines 2150–2180).
- **EV/EVSE audit (2026-06-15) — read end-to-end:** `domain_coordinators/energy.py` (`_apply_evse_battery_hold` at :2453–2470, EV battery-drain pause at :2671–2672, breaker invariant at :2615–2616 + :2959, post-decision arbitrage dispatch at :3106–3113, inclement-branch insertion at :2530); `domain_coordinators/energy_pool.py` (6 `_paused_by_*` sets at :196–272, off-peak ensure-on guard, resume-handoff chains at :559–563 / :755–759 / :849–853, EV TOU pause at :459); `domain_coordinators/energy_battery.py` static `self._battery.reserve_soc` at :174 vs `_result(reserve_level=...)` at :2700–2713.

### Prior-art greps + verdicts (REUSED vs NEW)

| Proposed addition | Grep run | Verdict | Reference |
|---|---|---|---|
| Storm/inclement detection helper | `storm\|inclement\|nws_alert` across `custom_components/` | **REUSED** the *mechanism* (storm short-circuit branch + BACKUP/SELF_CONSUMPTION + pre-charge result) at `energy_battery.py:2447–2464`. **NEW** the *detection function* — `has_storm_forecast()` at `energy_battery.py:648–659` is single-entity + binary + hardcoded condition set and will be **superseded** by `InclementFusion.decide() → InclementDecision`. | energy_battery.py:648, 2447 |
| Enphase Storm Guard read | `enphase\|storm_guard\|StormGuard` across `custom_components/` | **CONFIRMED ABSENT** — URA does not currently read Storm Guard. No regression on removal of dependency. | (no matches) |
| Multi-entity weather election | `WeatherProviderManager` | **REUSED** — manager already ranks `CONF_ENERGY_WEATHER_ENTITY` + `CONF_ENERGY_WEATHER_FALLBACK_1` + `CONF_ENERGY_WEATHER_FALLBACK_2`, tracks `WeatherProviderHealth`, applies `CONF_WEATHER_STALENESS_MAX_HOURS`, emits `SIGNAL_WEATHER_DIVERGENCE_DETECTED`. The storm cross-check must route through this manager. | weather_manager.py:38–52, 60–68 |
| TOU period awareness | `tou_period`, `peak_ahead_before_offpeak` in `energy_battery.py` | **REUSED** — `tou_period` is already passed to `determine_mode` (peak branch at `energy_battery.py:2468`, mid_peak at `:2489`, off_peak at `:2581`); `self._tou.peak_ahead_before_offpeak(now)` at `:2506` and `:2533` already provides the "is real peak ahead before next off_peak" lookahead the hold-depth ladder needs. **NEW** — wire the TOU period + peak-ahead lookahead into the inclement decision, not into a new TOU primitive. | energy_battery.py:2468, 2489, 2506, 2581; energy_tou.py:247 |
| **Solar SURPLUS (net-of-house-load) projection for recoverability (FIN-2)** | `_expected_solar_surplus_pct\|_should_attain_peak_buffer\|SOLAR_CAPTURE_FACTOR` in `energy_battery.py` | **REUSED** — `_expected_solar_surplus_pct(now, mins)` at `energy_battery.py:1362` returns **%SOC of expected solar capture into the battery** over a `[now, boundary]` window. It is already the v5.3.8 attainability machinery: forecast Solcast sliced by overlap window × `SOLAR_CAPTURE_FACTOR=0.5` to absorb losses + non-battery house load. **This is the correct primitive — it nets house load by construction.** The "raw solcast_remaining" approach in the prior revision DOUBLE-COUNTED house consumption and overstated recoverability. `_should_attain_peak_buffer` at `energy_battery.py:1587` is the canonical caller pattern (observed-rate term + surplus term). | energy_battery.py:1362, 1587, 1660 |
| Solar horizon — remaining-today + tomorrow forecast | `solcast_remaining`, `solcast_tomorrow`, `classify_tomorrow_solar` | **REUSED for tomorrow-class only** — `self.classify_tomorrow_solar()` at `energy_battery.py:531` still gates the overnight-fallback path. Raw `solcast_remaining` is NO LONGER consulted directly for the "recoverable today" branch (superseded by `_expected_solar_surplus_pct` per FIN-2). | energy_battery.py:500–558 |
| Sunset / dusk awareness | `astral`, `get_astral_event_date` | **REUSED** the HA `astral`/`sun` helper pattern already in `automation.py:1037, 1481` (sunrise/sunset for covers). **NEW** wrapper inside `inclement.py` that returns "minutes until next sunset" — small (~10 LoC) and avoids cross-domain import from `automation.py`. | automation.py:1037, 1481 |
| Storm charge SOC threshold | `DEFAULT_STORM_CHARGE_THRESHOLD` | **REUSED** at `energy_battery.py:110, 2449`. Stays the per-hold-depth ceiling default; hold-depth ladder picks the floor. | energy_battery.py:45, 2449 |
| `storm_forecast` attr | `energy_battery.py:2906` | **REUSED key, REDEFINED semantics** — currently re-evaluates `has_storm_forecast()` per attribute read. Replaced with cached `decision.hold_depth != allow_discharge`; siblings added (`inclement_hold_depth`, `inclement_source`, `inclement_tier`, `inclement_expires_at`, `inclement_reserve_floor`, `inclement_reason`, `inclement_solar_horizon`). | energy_battery.py:2895–2910 |
| Config-flow weather step | `CONF_ENERGY_WEATHER_*` in `config_flow.py` | **REUSED** existing step ≈ 3220–3450. Add the new selectors there, with the 3 tuning knobs grouped under an **"Advanced" subsection** per FIN-1. | config_flow.py:3226, 3290–3293 |
| Inclement-state signal | `signals.py` grep for `STORM`, `INCLEMENT`, `ALERT` | **NEW** — no existing `SIGNAL_INCLEMENT_*`. Propose `SIGNAL_INCLEMENT_STATE_CHANGED` for future HVAC / EV / NM consumers without coupling them to battery internals. |
| **EV pause-ownership sets (audit)** | `_paused_by_` across `energy_pool.py` | **CONFIRMED — plan writes NO `_paused_by_*` set.** 6 existing sets at `energy_pool.py:196–272`; this cycle touches only battery mode/reserve, not EV pause ownership. Clean vs the #15/#16 collision class. | energy_pool.py:196–272 |

### Prior planning docs skimmed
- `docs/planning/PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md` — confirms no overlap; the Optimization Coordinator does not own storm/inclement decisions.
- No prior `PLANNING_*storm*` / `PLANNING_*weather*` / `PLANNING_*inclement*` planning doc exists.

### Memory bodies pulled (relevant)
- v4.7.x weather manager cycle ("Cycle A: ranked-list weather provider with failover") is shipped infrastructure.
- Memo `017_ev_offpeak_decisions_and_comfort_opt_coordinator.json` + the durable "solar-first; never drain battery into car; off_peak grid cheapest" principle — drives the **D-3 grid-precharge default = False** decision AND the **FIN-3 rung-gated overnight fallback** (off_peak holds cheaply; mid_peak / peak are the only rungs where recoverability earns its complexity).
- `project_day_boundary_tou_live.md` (v4.7.29) — established that the peak/mid_peak hold logic is regression-prone; reinforces Tier 2-DB elevation.
- v5.3.8 attainability lesson (memo #16 / the attainability fix): **raw forecast solar ≠ battery charge** because the house consumes most of it first. This is precisely why FIN-2 swaps the recoverability metric over to the solar-surplus helper that already nets load.
- **`_paused_by_*` collision-class memos (#15 / #16):** ownership sets must never be reused across pause sources. Audit verified this cycle does not write any pause set; any FUTURE storm-paused-EV revision MUST add a dedicated `_paused_by_storm` set with explicit precedence in the resume-handoff chains.

### Design docs read
- No `docs/Coordinator/Energy.md` / `docs/Coordinator/EnergyBattery.md` design doc exists. The precedence comment block at `energy_battery.py:2418–2440` is the de-facto design doc and **must be edited** as part of this cycle to reflect the hold-depth ladder.

---

## EV / EVSE interaction audit (clean bill of health)

Cross-coordinator audit run 2026-06-15 over `energy.py`, `energy_pool.py`, and `energy_battery.py` to verify the inclement cycle cannot collide with EV charging logic or the #15/#16 pause-ownership class. **Verdict: CLEAN.** This cycle touches only battery mode/reserve and writes NO `_paused_by_*` set. The 5 audit findings below are threaded into deliverables and reviewer framings.

### 1. EV battery-drain protection is intentionally NOT storm-tightened (operator decision 2026-06-15: "simpler is good") — NON-GOAL

- `partial_hold` raises the *commanded* `reserve_soc_number` entity via `_result(reserve_level=...)` at `energy_battery.py:2700–2713` but does **NOT** mutate the *static* `self._battery.reserve_soc` at `energy_battery.py:174`.
- The EV battery-drain pause reads the STATIC `reserve_soc` at `energy.py:2672` along with its own `_ev_battery_drain_soc` threshold (default 50) at `energy.py:2671`.
- Therefore the storm-elevated floor does **NOT** reach the EV drain comparison.
- **ACCEPTED AS-DESIGNED.** Battery→EV drain is already prevented during a charging EV by `_apply_evse_battery_hold` (`energy.py:2453–2470`, invoked at `:2530` after `determine_mode`), which pins reserve up to the captured EV-charge SOC.
- **Operator chose the simpler path** — no drain-threshold threading. Recorded as an explicit **non-goal** below.

### 2. `_apply_evse_battery_hold` precedence — reviewer-owned (framing B)

`_apply_evse_battery_hold` runs AFTER the inclement branch (called at `energy.py:2530`; implementation at `:2453–2470`) and rewrites the decision's reserve. **Must be `max()`-safe and can NEVER LOWER a `full_hold` / `partial_hold` `reserve_floor`.** Threaded into D5 acceptance + Reviewer B framing below.

### 3. Breaker chokepoint (Q3) — clean today, conditional on precharge

With `CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD=False` (default per D-I), the inclement branch returns `charge_from_grid=False` → does NOT trigger the breaker invariant / breaker chokepoint at `energy.py:2615–2616, :2959`, and the off-peak ensure-on guard (`grid_charge_on=False`) is unaffected. **Clean.**

**CONDITIONAL note:** if the operator ever sets grid-precharge ON, a storm `charge_from_grid=True` WOULD enter the breaker invariant path — the breaker-safety reviewer framing (B) must cover the precharge-ON case.

### 4. Pause-ownership guardrail (framing B) + explicit NON-GOAL

- Plan writes NO `_paused_by_*` set. Verified clean vs the 6 sets at `energy_pool.py:196–272`.
- **Explicit NON-GOAL:** this cycle does NOT pause EVs during storms. Q2 concluded `_apply_evse_battery_hold` + grid-serves-EV already protect the reserve.
- **GUARDRAIL for any FUTURE revision:** if storms should ever pause EVs, that revision MUST add a dedicated `_paused_by_storm` set with explicit precedence in the resume-handoff chains at `energy_pool.py:559–563, 755–759, 849–853` — **never reuse an existing set** (the #15/#16 collision-class lesson).

### 5. Arbitrage-handoff acceptance test — regression-prone seam (framing A / B)

`determine_arbitrage_actions(arbitrage_charging=pause_requested)` runs every tick in the post-decision dispatch at `energy.py:3106–3113`. When `determine_mode` returns a hold, `pause_requested` / `charge_from_grid` go False → the release/cleanup path fires → EVs are released, not orphaned. **This transition is the regression-prone seam.** Threaded as a new behavioral acceptance criterion in D5.

---

## Verified current state (load-bearing facts)

1. **URA does NOT consume Enphase Storm Guard.** Zero references in `custom_components/`. Removing operator's reliance on Storm Guard is a configuration action by the operator (in the Enphase app), not a code change. URA's job is to *replace the function* Storm Guard was performing — and to do it better via TOU + solar-horizon awareness.
2. **Storm detection today** = `EnergyBatteryCoordinator.has_storm_forecast()` at `energy_battery.py:648–659`. Reads `self._get_entity("weather", DEFAULT_WEATHER_ENTITY)` — **single entity**. Compares lowercased state against hardcoded set `{lightning, lightning-rainy, hail, tornado, hurricane, exceptional}`. Returns `bool`. Does NOT consult `WeatherProviderManager`. Does NOT read alerts. Does NOT consider TOU or solar horizon.
3. **Storm action today** = `determine_mode()` at `energy_battery.py:2447–2464`:
   - Storm + `soc < DEFAULT_STORM_CHARGE_THRESHOLD` (90) → `BATTERY_MODE_SELF_CONSUMPTION` with `charge_from_grid=True`, reserve = `self.reserve_soc`.
   - Storm + `soc >= 90` → `BATTERY_MODE_BACKUP` (hold).
   - Storm branch is checked **after grid-disconnect, before TOU/arbitrage**. Precedence comment at `:2418–2440` explicitly warns against reordering.
   - **Net effect today is a BINARY HOLD** — discharge is fully suppressed for the entire alert duration regardless of TOU period or whether sun is about to refill the battery anyway.
4. **TOU branches that hold-depth interacts with:**
   - `peak` branch at `energy_battery.py:2468` — currently always allows self_consumption discharge if `soc > reserve_soc`.
   - `mid_peak` branch at `:2489` — summer pre-peak HOLDS (`:2535`); shoulder/winter and summer post-peak DISCHARGE (`:2549`).
   - `off_peak` branch at `:2581` — arbitrage state machine OR drain-target fallback.
   - The inclement decision now **modulates the reserve floor** these branches pass to `_result(reserve_level=…)`, rather than wholesale replacing them. This preserves the precedence chain (grid_disconnect > inclement-full-hold > TOU > arbitrage) for the `full_hold` case, while `partial_hold` lets the TOU branch run but with an elevated floor.
5. **Solar-horizon signals available** (no new wiring needed):
   - `self._expected_solar_surplus_pct(now, mins)` (`:1362`) — **%SOC of expected solar SURPLUS into the battery** over a window, already nets house load via `SOLAR_CAPTURE_FACTOR=0.5`. **THIS IS THE FIN-2 PRIMITIVE.**
   - `self._should_attain_peak_buffer(...)` (`:1587`) — canonical caller showing the (observed-rate + surplus) projection pattern.
   - `self.classify_tomorrow_solar()` (`:531`) — `poor|fair|good` class for tomorrow, used for the overnight fallback only.
   - HA `sun.sun` entity for sunset time (read via astral helper, pattern from `automation.py:1037, 1481`).
6. **NWS Alerts sensor (operator's setup):** `sensor.nws_alerts_gps_30_3146_98_0159_nws_alerts_alerts`.
   - `state` = string-encoded integer count (e.g. `"1"`).
   - `attributes.Alerts` = list of dicts. Per-alert keys: `Event`, `Severity ∈ {Extreme, Severe, Moderate, Minor, Unknown}`, `Certainty ∈ {Observed, Likely, Possible, Unlikely, Unknown}`, `Status ∈ {Actual, Exercise, Test, Draft}`, `NWSCode`, `Headline`, `Onset / Expires / Ends` (ISO timestamps), `AreasAffected`, `Description`, `Instruction`.
   - Live right now: `Event=Flood Watch, Severity=Severe, Certainty=Possible`, `Onset=2026-06-11T19:15`, `Ends=2026-06-12T19:00` — the natural in-the-wild test fixture.
7. **Dynamic Weather entity** `weather.madroneweather_tracker_dynamic_weather_madroneweather_tracker` is NOT yet wired into `CONF_ENERGY_WEATHER_*`. Config migration deliverable (D0), not a code change.
8. **EV/EVSE interaction (audit 2026-06-15):** `_apply_evse_battery_hold` (`energy.py:2453–2470`) runs after the inclement branch (`:2530`) and rewrites the decision's reserve — must be `max()`-safe. EV battery-drain pause (`:2671–2672`) reads STATIC `self._battery.reserve_soc` (`:174`), not the elevated commanded reserve — accepted as-designed (see audit §1). Post-decision `determine_arbitrage_actions` runs every tick (`:3106–3113`) — the release-on-hold path is the regression-prone seam (see audit §5).

---

## Design

### Classifier flow — Event-type OUTAGE-RELEVANCE is the PRIMARY gate

The CAP standard (Common Alerting Protocol used by NWS) defines **Severity, Certainty, and Urgency as three INDEPENDENT axes**. A high-Severity alert is NOT necessarily an outage threat — e.g. a `Flood Watch` (`Severity=Severe`, `Certainty=Possible`) is high-severity but, for this elevated property, a weak outage predictor (flooding does not cut power here). Equally, "Watch" vs "Warning" is a **NWS product-type designation**, not a CAP severity level — it primarily encodes certainty of occurrence.

The classifier therefore gates by **Event power/outage-relevance FIRST**, not by Severity, Certainty, or product-type name:

```
ALERT  →  (1) OUTAGE-RELEVANCE GATE
              ┌───────────────────────────────────────────────────┐
              │ Is alert.Event name a case-insensitive substring  │
              │ match against CONF_INCLEMENT_POWER_THREAT_EVENTS? │
              └─────────────┬──────────────────────┬──────────────┘
                            │                      │
                          PASS                     FAIL
                            │                      │
                            ▼                      ▼
              (2) CERTAINTY TIERING          tier = NOTICE
              ┌───────────────────────┐      (informational only;
              │ Observed | Likely     │       never holds battery)
              │   → warn-tier (firm)  │
              │ Possible | Unlikely   │
              │   → watch-tier        │
              │   (needs corroboration│
              │    per CONF_INCLEMENT │
              │    _WATCH_REQUIRES_   │
              │    CORROBORATION)     │
              │                       │
              │ (Watch/Warning product│
              │  type in Event name   │
              │  FOLDS INTO certainty:│
              │  a "Warning" product  │
              │  is treated as higher │
              │  certainty even if    │
              │  Certainty field is   │
              │  conservative.)       │
              └───────────┬───────────┘
                          ▼
              (3) SEVERITY NOISE FILTER
              ┌────────────────────────┐
              │ Severity >= CONF_      │
              │ INCLEMENT_WARN_MIN_    │
              │ SEVERITY (default      │
              │ "Severe")?             │
              │  - If NO → demote one  │
              │    tier (warn→watch,   │
              │    watch→notice)       │
              │  Severity is a         │
              │  SECONDARY NOISE FILTER│
              │  ONLY — never the gate │
              └───────────┬────────────┘
                          ▼
                  AlertClassification(tier, ...)
```

**Critical design property:** Severity is a noise filter, not the gate. Watch vs Warning is a product type, not a severity level. Only Events whose name matches the operator-curated **power-threat list** can ever produce a hold; everything else is `NOTICE`.

### High-level fusion model (UPDATED — hold depth, not binary hold)

```
   ┌─────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
   │ NWS Alerts      │   │ WeatherProviderMgr   │   │ Solar/Sun signals    │
   │ attributes.     │   │ primary + 2 fallbacks│   │ surplus_pct(window), │
   │ Alerts[]        │   │ health, staleness,   │   │ classify_tomorrow,   │
   │ Event/Severity/ │   │ divergence, current  │   │ sun.sun (sunset)     │
   │ Certainty/      │   │ condition per        │   │                      │
   │ Status/Onset/   │   │ provider             │   │                      │
   │ Expires/Ends    │   └──────────┬───────────┘   └──────────┬───────────┘
   └────────┬────────┘              │                          │
            │                       │                          │
   ┌────────▼─────────┐  ┌──────────▼──────────┐    ┌──────────▼──────────┐
   │ AlertClassifier  │  │ ConditionElector    │    │ SolarHorizon        │
   │ outage gate →    │  │  → corroborated     │    │  → recoverable      │
   │ certainty →      │  │     stormy? bool    │    │     (SURPLUS-based, │
   │ severity filter  │  │   + provider count  │    │      net of house   │
   │  → tier ∈        │  │   + staleness OK?   │    │      load)          │
   │  {none, notice,  │  └──────────┬──────────┘    │   + surplus_pct     │
   │   watch, warn}   │             │               │   + minutes_to_dusk │
   │  + Onset/Expires │             │               └──────────┬──────────┘
   └────────┬─────────┘             │                          │
            │           ┌───────────▼───────┐                  │
            └───────────►   TOU period      ◄──────────────────┘
                        │   (passed in;     │   (only consulted for
                        │   off_peak skips  │    mid_peak / peak rungs
                        │   recoverability  │    per FIN-3)
                        │   check)          │
                        └──────────┬────────┘
                                   ▼
                       ┌──────────────────────────┐
                       │ InclementFusion          │
                       │ decide(tier, period,     │
                       │        horizon) →        │
                       │   InclementDecision      │
                       │     hold_depth ∈         │
                       │       {full_hold,        │
                       │        partial_hold,     │
                       │        allow_discharge}  │
                       │     grid_precharge: bool │
                       │     tier, source,        │
                       │     expires_at,          │
                       │     reserve_floor: int,  │
                       │     reason: str          │
                       └───────────┬──────────────┘
                                   ▼
                  (consumed at energy_battery.py:2447–2464 +
                   threaded into peak / mid_peak branches as
                   an elevated reserve_floor for partial_hold)
```

### The hold-depth ladder (NEW — replaces binary hold)

Three rungs. Each rung passes a different `reserve_floor` into the determine_mode branches:

| Rung | Effect | reserve_floor | Where consumed |
|---|---|---|---|
| `full_hold` | Short-circuits at the inclement branch (current behavior). Returns `BATTERY_MODE_BACKUP` immediately; TOU branches don't run. | `peak_buffer_target` or 100 (whichever set) | `energy_battery.py:2447–2464` (the slot today's binary hold uses) |
| `partial_hold` | Lets the TOU branch run, but with an **elevated reserve floor** = `max(self.reserve_soc, CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR)` (**default 50%** per FIN-1). Peak/mid_peak discharge proceeds but stops earlier — more backup retained, some peak savings still realized. | configurable, **default 50%** | Threaded into peak branch at `:2474`, mid_peak discharge at `:2562, 2577`, replacing `self.reserve_soc` in `reserve_level=` |
| `allow_discharge` | No override. TOU branches run with normal `self.reserve_soc`. | `self.reserve_soc` (unchanged) | (no change) |

### `SolarHorizon.recoverable` — SURPLUS-based (FIN-2)

**`SolarHorizon.recoverable` is computed ONLY when the rung asks for it** (mid_peak / peak per FIN-3). Off_peak callers SHORT-CIRCUIT to `recoverable=None / not_consulted` and skip the projection entirely. When consulted:

1. **Compute the risk window.** `mins_to_window = minutes from now until min(alert.Expires, next_sunset)`. This is the horizon over which we need solar to refill what `partial_hold` would let us discharge.
2. **Project surplus into battery over the risk window.** `surplus_pct = self._expected_solar_surplus_pct(now, mins_to_window)` — REUSES `energy_battery.py:1362`. This **already nets house load** (Solcast × overlap fraction × `SOLAR_CAPTURE_FACTOR=0.5`). No raw-solar over-estimation.
3. **Define the discharge headroom that partial_hold would PERMIT.** `permitted_discharge_pct = max(0, current_soc - CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR)` — i.e. how many %SOC partial_hold lets the TOU branch eat into before stopping.
4. **Recoverability check (today-path):**
   `recoverable = surplus_pct >= permitted_discharge_pct + CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT`
   The margin is a conservative buffer (default **5 %SOC**) — surplus must beat the permitted discharge by the margin, not merely match it. This structurally raises the bar so a cloudy/high-load day cannot falsely read "recoverable" the way the prior raw-8-kWh threshold could.
5. **Overnight-fallback path (today-path failed):** Only if `classify_tomorrow_solar() in {fair, good}` AND `alert.Expires < tomorrow_sunrise + 2h` (i.e. discharge happens overnight and we expect sun to refill in the morning before the next mid_peak / peak rung). Encodes "we can refill in the morning."
6. **Else:** `recoverable = False`.

**Why this is conservative vs the prior raw-kWh metric:** the v5.3.8 helper uses `SOLAR_CAPTURE_FACTOR=0.5` (already half the raw forecast, absorbing losses + non-battery load) AND we further require a 5-%SOC margin above the permitted-discharge SOC. The OLD threshold (`raw solcast_remaining >= 8 kWh`) would mark a cloudy 9 kWh day as "recoverable" while in practice ≤4 kWh of that would land in the battery; the NEW formulation refuses that day.

**`CONF_INCLEMENT_RECOVERABLE_KWH_TODAY` is DELETED.** Replaced by `CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT` (units = %SOC margin above permitted discharge; default 5).

### Hold-depth decision matrix (tier × TOU × solar horizon) — FIN-3 applied

Tier here is the OUTPUT of the gate→certainty→severity classifier flow above. `warn` = passed-the-outage-gate + high-certainty (Observed/Likely, or "Warning" product type folding in). `watch` = passed-the-outage-gate + low-certainty (Possible/Unlikely). `notice` = failed-the-outage-gate (Event is not in the power-threat list) OR severity-filter demotion. Watch-corroboration is a separate sub-axis determined by `ConditionElector`.

**FIN-3 rung gating:** the SolarHorizon recoverability check is **only consulted for `mid_peak` and `peak` rows**. `off_peak` rows are "hold readily" (full or near-full) regardless of recoverability — holding during off_peak forgoes no arbitrage discharge revenue (off_peak doesn't discharge for savings), so the recoverability question is moot and cheap to skip. The matrix cells below marked **"n/a (off_peak)"** for the recoverable column reflect this.

| Tier | TOU period | Solar recoverable? | Hold depth | `grid_precharge` |
|---|---|---|---|---|
| `warn` (passed gate, high certainty) | off_peak | n/a (off_peak) | **full_hold** | True if SOC<90 (cheap energy) |
| `warn` | mid_peak | not consulted (warn=always hold) | **full_hold** | False (don't burn mid_peak grid) |
| `warn` | peak | not consulted (warn=always hold) | **full_hold** | False (never grid-fill at peak) |
| `watch` (passed gate, low certainty, corroborated) | off_peak | n/a (off_peak) | **full_hold** | True if SOC<90 |
| `watch` (corroborated) | mid_peak | recoverable | **partial_hold** | False |
| `watch` (corroborated) | mid_peak | not recoverable | **full_hold** | False |
| `watch` (corroborated) | peak | recoverable | **partial_hold** | False |
| `watch` (corroborated) | peak | not recoverable | **full_hold** | False |
| `watch` (uncorroborated) | off_peak | n/a (off_peak) | **partial_hold** | False |
| `watch` (uncorroborated) | mid_peak / peak | any | **allow_discharge** | False |
| `notice` (failed gate OR severity-demoted) | any | n/a | **allow_discharge** | False |
| `none` | any | n/a | **allow_discharge** | False |
| Condition-only (NWS sensor absent) ≥2 healthy providers stormy | off_peak | n/a (off_peak) | **partial_hold** | False |
| Condition-only | mid_peak / peak | any | **allow_discharge** | False |

Matrix rows stay (warn / watch-corroborated / watch-uncorroborated / condition-only / notice) but "warn vs watch" is now **certainty-derived** (warn = passed-gate + high-certainty; watch = passed-gate + low-certainty needing corroboration) — NOT a bare Watch-vs-Warning name check. **Off_peak rows never call into `SolarHorizon.recoverable` (FIN-3).** Warn rows hold at any TOU period without consulting recoverability (high-certainty alerts always hold).

This matrix is the **load-bearing default set** — see L-B Decisions D-A through D-O for operator sign-off.

**Where in determine_mode this evaluates:** Right at `energy_battery.py:2447`. The fused decision is computed once per coordinator tick (cached on `self._last_inclement_decision`). The branch becomes:

```python
decision = self._inclement_decision()  # cached per tick
if decision.hold_depth == "full_hold":
    # current behavior — preserved as the warn-tier path
    if decision.grid_precharge and soc is not None and soc < DEFAULT_STORM_CHARGE_THRESHOLD:
        return self._result(BATTERY_MODE_SELF_CONSUMPTION, decision.reason,
                            current_mode, charge_from_grid=True,
                            reserve_level=decision.reserve_floor, season=season)
    return self._result(BATTERY_MODE_BACKUP, decision.reason, current_mode,
                        reserve_level=decision.reserve_floor, season=season)
# partial_hold falls through to TOU branches BUT with an elevated effective_reserve
effective_reserve = max(self.reserve_soc, decision.reserve_floor)
# peak / mid_peak / off_peak branches read effective_reserve in place of self.reserve_soc
```

The TOU branches at `:2474, 2481, 2562, 2577` get a small refactor to read `effective_reserve` instead of `self.reserve_soc`. This is a 5-site, mechanical change with no behavior shift when `decision.hold_depth == "allow_discharge"` (because `decision.reserve_floor == self.reserve_soc` in that case). Reviewer B verifies the precedence comment block still describes reality. **NOTE per EV audit §2:** `_apply_evse_battery_hold` is invoked at `energy.py:2530` AFTER `determine_mode` returns and rewrites the decision's reserve. It must be `max()`-safe so a full_hold/partial_hold `reserve_floor` can NEVER be lowered. If `evse_hold_soc > reserve_floor` the hold wins (fine); if `full_hold` returns BACKUP mode, the evse-hold rewrite must NOT downgrade it.

### Hold DURATION = alert's own Expires/Ends (NOT a fixed timer)

The fix for the Enphase multi-day stale lock: hold duration is **bounded by the alert's `Expires` / `Ends` timestamps** (whichever is sooner per the NWS schema; both are parsed). The `AlertClassification` carries `expires_at = min(Ends, Expires)` per-alert; the fused decision's `expires_at` is the `min()` across contributing alerts. Each coordinator tick re-evaluates — when the soonest contributor expires, that alert drops out; when all contributors expire, the alert path returns `tier=none`. **No fixed multi-hour/multi-day timer exists in any code path.**

Condition-only path persists while ≥2 healthy providers report stormy + a short decay (`CONF_INCLEMENT_CONDITION_DECAY_MINUTES`, default 30 min) after providers clear — re-evaluated each tick.

**Acceptance criterion (live):** A hold cannot outlive the alert's `Expires`. For the current live Flood Watch (Ends 2026-06-12T19:00), if any hold logic triggers, it MUST drop within one tick of 19:00 tomorrow.

### Fire alerts = notice-only by default (because they're absent from the power-threat list)

Fire Weather Watch / Red Flag Warning default to **notice-only** purely because their Event names are NOT in `CONF_INCLEMENT_POWER_THREAT_EVENTS` — they fail the outage-relevance gate and exit as `NOTICE`. There is **no separate fire-handling code path** — the consolidated power-threat-events list is the single mechanism.

To escalate fire alerts to hold-eligible (e.g. if a PSPS / utility-outage surface is added in the future, or the property moves to a wildfire-prone area), the operator simply **adds** the string `"Red Flag"` or `"Fire Weather"` to `CONF_INCLEMENT_POWER_THREAT_EVENTS`. To make sure flood NEVER holds, the string `"Flood"` is simply absent from the list.

Helper text on `CONF_INCLEMENT_POWER_THREAT_EVENTS` (see knob table) explicitly explains: fire alerts are notice-only by default and can be added.

### Config = thoughtful plain-English named buckets — with "Advanced" subsection (FIN-1)

Per `feedback_configurability_clarity.md` (named-bucket dropdowns + plain-English helper text) and `feedback_parsimonious_room_config.md` (lean the surface). Final knob list — **7 knobs**, of which **3 are grouped under an "Advanced" subsection** (operator: "Advanced Config") so they don't clutter the primary surface:

**Primary surface (4 knobs):**

| Knob | Type | Default | Label (operator-facing) | Helper text (operator-facing) |
|---|---|---|---|---|
| `CONF_INCLEMENT_NWS_ALERTS_ENTITY` | entity selector (`sensor`) | unset | NWS Alerts sensor | The Home Assistant sensor that exposes National Weather Service alerts (e.g. `sensor.nws_alerts_…`). Leave blank to fall back to weather-condition cross-checks only. |
| `CONF_INCLEMENT_POWER_THREAT_EVENTS` | text (multi-line) | `["Tornado", "Severe Thunderstorm", "Ice Storm", "Winter Storm", "High Wind", "Extreme Wind", "Hurricane", "Blizzard"]` | Event types that can hold the battery | One per line. Case-insensitive substring match against the NWS Event name (so `Severe Thunderstorm` matches both `Severe Thunderstorm Warning` AND `Severe Thunderstorm Watch`). This is the FIRST gate — any alert whose Event name does NOT match an entry here is informational only and will not hold the battery, regardless of how severe it sounds. Fire-weather alerts (Red Flag Warning, Fire Weather Watch) are notice-only by default; ADD `Red Flag` or `Fire Weather` here to make them hold-eligible. Flood alerts are absent by default for this elevated property; ADD `Flood` if your location is power-vulnerable to flooding. |
| `CONF_INCLEMENT_WARN_MIN_SEVERITY` | select | "Severe" | Minimum severity that can hold the battery | Secondary noise filter applied AFTER the Event-type gate. Choose the lowest NWS Severity value that should still produce a hold. "Extreme" — only catastrophic events; "Severe" (recommended) — Severe + Extreme; "Moderate" — Moderate + Severe + Extreme; "Minor" — any non-Unknown severity. NOTE: this filter never overrides the Event-type gate — a non-power-threat event is always informational regardless of severity. |
| `CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD` | boolean | False | Charge from grid to fill the battery during holds | When ON, a warning-tier hold will pull from grid during off_peak hours to top up the battery to ~90% before the storm. When OFF, the battery is held at whatever level the sun/arbitrage put it at — no expensive grid energy is used. URA defaults OFF (solar-first philosophy). |

**Advanced subsection (3 knobs)** — grouped under a collapsible / explicitly-marked "Advanced" section in the config-flow step (FIN-1). All exposed (operator chose expose-all over hardcoding):

| Knob | Type | Default | Label (operator-facing) | Helper text (operator-facing) |
|---|---|---|---|---|
| `CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR` | number (0-100) | **50** | Reserve floor during partial holds (%) | When URA decides to partially hold (e.g. low-certainty watch during peak with sun ahead), how much battery to keep in reserve. **50% (default)** — preserves a robust overnight backup while still allowing some peak savings. Set lower for more peak savings, higher for more backup. Note: changed from 40% in earlier revisions — operator chose 50% as the stronger backup posture. |
| `CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT` | number (0-30 %SOC) | **5** | Solar-surplus margin for "recoverable" (% SOC) | How much projected solar SURPLUS (net of house load) must EXCEED what a partial hold would let URA discharge, before that discharge counts as "recoverable" by sun before nightfall. Default 5% SOC. URA reuses the v5.3.8 attainability surplus projection (which already nets house load via a 0.5 capture factor), then requires this extra margin so a cloudy / high-load day doesn't falsely read as recoverable. Only consulted during mid_peak / peak rungs — off_peak holds without consulting recoverability. |
| `CONF_INCLEMENT_CONDITION_CORROBORATION_MODE` | select | "Majority of healthy providers" | Local condition cross-check | "Any provider stormy" — over-eager; "Majority of healthy providers" — balanced (recommended); "All providers stormy" — under-eager (one stale provider blocks). |

**Hidden / hardcoded (NOT exposed):**

- `CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION` — operator confirmed default **True**, exposed as a Primary toggle in earlier revision; **kept ON, hardcoded** (operator may flip if needed; lifting to UI later is cheap). [REVISION NOTE: if operator wants this re-exposed before build, surface in build kickoff — not in plan churn.]
- `CONF_INCLEMENT_CONDITION_DECAY_MINUTES` — hardcoded 30 min.

**Confirmation of 4 toggles (per operator request):**
- Watch-requires-corroboration: **ON** (hardcoded; default True).
- Grid-precharge-on-hold: **OFF** (Primary surface, default False — solar-first).
- Warn-min-severity: **"Severe"** (i.e. "Severe + likely" capturing the operator's "Severe+ likely certainty" framing — Severe is the floor, Likely is the certainty band that promotes to warn).
- Condition cross-check: **"Majority of healthy providers"** (Advanced surface, default).

**7 knobs total** (3 of which are Advanced). `CONF_INCLEMENT_RECOVERABLE_KWH_TODAY` is **DELETED** (replaced by SURPLUS_MARGIN_PCT). `CONF_INCLEMENT_PROMOTED_EVENTS` remains deleted from prior revision. Operator pruning pass before build per parsimony rule remains an option — but the Advanced grouping is the parsimony lever.

---

## Deliverables

### D0 — Operator config migration (Dynamic Weather + NWS alerts entity) — **PRE-REQ, NO CODE**

Operator updates URA options (Energy → Weather Providers step) to:
- Set `CONF_ENERGY_WEATHER_FALLBACK_1` or `_2` to `weather.madroneweather_tracker_dynamic_weather_madroneweather_tracker`.
- Set the new `CONF_INCLEMENT_NWS_ALERTS_ENTITY` (added in D2) to `sensor.nws_alerts_gps_30_3146_98_0159_nws_alerts_alerts`.

**Acceptance:** Dynamic Weather shows `WeatherProviderHealth.HEALTHY`; `binary_sensor.ura_weather_divergence` stable.

### D1 — `AlertClassifier` (new helper in `domain_coordinators/inclement.py`)

Pure function module. Implements the gate→certainty→severity flow from the Design section. Parses `attributes.Alerts`, returns:

```python
@dataclass(frozen=True)
class AlertClassification:
    tier: Literal["warn", "watch", "notice", "none"]
    contributing_events: tuple[str, ...]
    max_severity: str
    max_certainty: str
    expires_at: datetime | None    # min(Ends, Expires) across contributors
    raw_alert_count: int
    gated_out_events: tuple[str, ...]   # events that failed the outage gate (for observability/debugging)
```

Classifier steps (in order):
1. **Outage-relevance gate.** For each alert, case-insensitive substring match `alert.Event` against `CONF_INCLEMENT_POWER_THREAT_EVENTS`. Fail → contributes to `gated_out_events`, no tier impact.
2. **Certainty tiering** for events that passed: Observed/Likely → warn-candidate; Possible/Unlikely → watch-candidate. Product-type folding: if Event name ends in `Warning` and the Certainty field is conservative (Possible), still promote to warn-candidate.
3. **Severity noise filter:** if `Severity < CONF_INCLEMENT_WARN_MIN_SEVERITY`, demote one tier (warn→watch, watch→notice).
4. Aggregate to the final `tier` = max across contributors.

Robustness: None-safe; missing/empty/non-list `Alerts`; missing per-alert fields fall back to `"Unknown"`; naive timestamps coerced via `dt_util`; drop `Status != "Actual"`; drop expired alerts.

**Acceptance criteria:**
- **Test:** `tests/test_inclement_alert_classifier.py::test_flood_watch_severe_possible_returns_NOTICE_because_flood_fails_gate` (live operator alert as fixture — the headline correctness test).
- **Test:** `::test_severe_thunderstorm_warning_observed_returns_warn_tier` (passes gate).
- **Test:** `::test_severe_thunderstorm_watch_possible_corroboration_required_returns_watch_tier` (passes gate, low certainty).
- **Test:** `::test_tornado_warning_observed_returns_warn_tier`.
- **Test:** `::test_red_flag_warning_returns_NOTICE_by_default_because_fire_absent_from_list`.
- **Test:** `::test_red_flag_warning_returns_warn_tier_when_operator_adds_red_flag_to_power_threat_list`.
- **Test:** `::test_severity_below_min_demotes_one_tier` (Moderate Severe-Thunderstorm-Warning → watch).
- **Test:** `::test_severity_never_overrides_gate` (Extreme Flood Watch still → NOTICE).
- **Test:** `::test_expired_alert_excluded`, `::test_exercise_status_excluded`.
- **Test:** `::test_malformed_alerts_attr_returns_none_tier_no_exception` (covers `None`, `[]`, `[{}]`, `"not a list"`).
- **Test:** `::test_keyword_match_case_insensitive`.
- **Test:** `::test_warning_product_type_folds_into_higher_certainty`.
- **Live (headline correctness):** With the LIVE `Flood Watch` (Severity=Severe, Certainty=Possible) present, `inclement_tier=notice`, `hold_depth=allow_discharge`, `inclement_gated_out_events` includes "Flood Watch", and the battery DISCHARGES normally through mid_peak / peak. **This is the "beats Enphase" proof.**

### D2 — `SolarHorizon` (new helper in `inclement.py`) — FIN-2 + FIN-3

```python
@dataclass(frozen=True)
class SolarHorizon:
    recoverable: bool | None       # None when not consulted (off_peak per FIN-3)
    surplus_pct_to_window: float | None   # %SOC of expected solar surplus into battery over the risk window
    permitted_discharge_pct: float | None # %SOC partial_hold would let TOU discharge
    margin_pct: float | None              # CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT
    tomorrow_class: str           # poor|fair|good|unknown
    minutes_to_sunset: int | None
    minutes_to_risk_window_end: int | None
    reason: str                   # one-line for log/attr (e.g. "off_peak_skip", "today_surplus_ok", "overnight_fallback_tomorrow_good")
```

**Computation (FIN-2 + FIN-3):**
1. **Rung gate (FIN-3):** if caller is `off_peak`, return `SolarHorizon(recoverable=None, reason="off_peak_skip", ...)` immediately — DO NOT call `_expected_solar_surplus_pct`.
2. For `mid_peak` / `peak` callers:
   a. `mins_to_window = minutes from now until min(alert.Expires, next_sunset)`.
   b. `surplus_pct = battery._expected_solar_surplus_pct(now, mins_to_window)` — **REUSES `energy_battery.py:1362`. This nets house load by construction (SOLAR_CAPTURE_FACTOR=0.5).**
   c. `permitted_discharge_pct = max(0, current_soc - CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR)`.
   d. `today_recoverable = surplus_pct >= permitted_discharge_pct + CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT`.
3. **Overnight fallback** (today_recoverable is False): `classify_tomorrow_solar() in {fair, good}` AND alert `Expires < tomorrow_sunrise + 2h`.
4. `recoverable = today_recoverable OR overnight_fallback`.

`SolarHorizon` is a pure-derivation helper that receives a reference to the battery coordinator (for `_expected_solar_surplus_pct` + `classify_tomorrow_solar`) and the `tou_period`. No new IO outside those reads.

**Acceptance:**
- **Test:** `::test_off_peak_caller_returns_recoverable_None_short_circuits_surplus_call` — verifies FIN-3 short-circuit (mock `_expected_solar_surplus_pct` to assert NOT called).
- **Test:** `::test_mid_peak_recoverable_true_when_surplus_exceeds_permitted_plus_margin`.
- **Test:** `::test_mid_peak_recoverable_false_when_surplus_only_matches_permitted_no_margin` — proves the margin is load-bearing.
- **Test:** `::test_peak_recoverable_false_when_surplus_zero_post_sunset`.
- **Test:** `::test_overnight_fallback_recoverable_when_tomorrow_good_and_expires_before_sunrise_window`.
- **Test:** `::test_uses_expected_solar_surplus_pct_helper_not_raw_solcast_remaining` — Reviewer A's correctness guard.
- **Live:** Attr `inclement_solar_horizon.surplus_pct_to_window` populated during a real mid_peak watch; `recoverable=None` and `reason="off_peak_skip"` during off_peak watches.

### D3 — Config-flow knobs (Energy → Weather Providers step extension)

Add the 7 knobs from §"Config" above to the existing weather step at `config_flow.py:3220–3450` (do NOT fork). Each knob ships with the operator-facing label + helper text as written above.

**FIN-1 layout:** Group the **3 Advanced knobs** (`CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR`, `CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT`, `CONF_INCLEMENT_CONDITION_CORROBORATION_MODE`) under an explicit "Advanced" subsection / section_marker / collapsible block (use the existing HA `section` schema construct if the schema version supports it; otherwise insert a labeled spacer + section comment). The 4 Primary knobs render above. Operator surface stays clean for the common case.

**Acceptance:** Round-trip via options flow; defaults applied cleanly for existing installs; config-flow runtime smoke (per `project_config_flow_runtime_tests_backlog.md` pattern); default value of `CONF_INCLEMENT_POWER_THREAT_EVENTS` matches the 8-event list verbatim; `CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR` default is **50** (not 40); Advanced subsection renders distinctly from Primary.

### D4 — `ConditionElector` (extension of `WeatherProviderManager`)

```python
def current_storm_condition(self) -> StormConditionResult: ...

@dataclass(frozen=True)
class StormConditionResult:
    is_stormy: bool
    healthy_provider_count: int
    stormy_provider_count: int
    contributing_conditions: tuple[str, ...]
    mode_used: str   # any|majority|unanimous
```

Broadened condition set (hardcoded in v1): `{lightning, lightning-rainy, hail, tornado, hurricane, exceptional, pouring, snowy-rainy}`. Legacy set preserved as subset — no regression for installs without alerts sensor.

**Acceptance:** majority/unanimous/any unit tests + unhealthy-provider exclusion test; live attr `condition_stormy`.

### D5 — `InclementFusion.decide()` + supersede `has_storm_forecast()`

```python
@dataclass(frozen=True)
class InclementDecision:
    hold_depth: Literal["full_hold", "partial_hold", "allow_discharge"]
    grid_precharge: bool
    tier: str                         # warn|watch|notice|none
    source: str                       # alert|condition|both|none
    contributing_event: str | None
    expires_at: datetime | None
    reserve_floor: int                # 0-100 — the floor passed to determine_mode
    reason: str
    solar_horizon: SolarHorizon       # embedded for observability
```

**Call-site migration at `energy_battery.py:2447–2464`** (see §"Where in determine_mode this evaluates" above). The TOU branches at `:2474, 2481, 2562, 2577` are refactored to read `effective_reserve = max(self.reserve_soc, decision.reserve_floor)` instead of `self.reserve_soc`. **Per-tick caching** on `self._last_inclement_decision` — attribute reads do NOT re-evaluate.

**FIN-3 wiring inside `InclementFusion.decide()`:** the `SolarHorizon` is constructed lazily, AFTER the (tier, tou_period) is known. For tier=`warn` or tou_period=`off_peak`, recoverability is never consulted — the matrix row determines hold_depth directly. Only the `watch + mid_peak/peak` and (future) condition-only paths actually instantiate the SURPLUS-projected SolarHorizon.

`has_storm_forecast()` is **deleted** (private method, no external consumers verified via grep). The `storm_forecast` ATTRIBUTE KEY is kept for back-compat: `storm_forecast = (decision.hold_depth != "allow_discharge")`.

The precedence comment block at `:2418–2440` is edited to describe the hold-depth ladder and the effective_reserve threading.

**Acceptance criteria:**
- **Verify:** Precedence unchanged — grid_disconnect still wins over `full_hold`.
- **Verify:** `full_hold` short-circuits TOU branches exactly as today's storm path does.
- **Verify:** `partial_hold` lets TOU branches run with elevated reserve floor (default **50%** per FIN-1); net effect is earlier discharge stop, not no-discharge.
- **Verify:** `allow_discharge` produces byte-identical behavior to a no-storm tick (regression guard — Reviewer A focus).
- **Verify:** Hold drops within one tick of `decision.expires_at` passing.
- **Verify (FIN-3):** off_peak watch decisions DO NOT call `_expected_solar_surplus_pct` (Reviewer B mock-assert).
- **Verify (FIN-2):** mid_peak/peak watch decisions DO call `_expected_solar_surplus_pct` and the recoverable bool uses (surplus_pct >= permitted + margin) NOT raw solcast_remaining.
- **Verify (EV audit §2 — `_apply_evse_battery_hold` precedence):** the post-`determine_mode` invocation at `energy.py:2530` is `max()`-safe and can NEVER LOWER a `full_hold` / `partial_hold` `reserve_floor`. If `evse_hold_soc > reserve_floor`, the EV hold wins (correct). If `full_hold` returned `BATTERY_MODE_BACKUP`, the evse-hold rewrite must NOT downgrade the mode. Add a unit test asserting `max(full_hold.reserve_floor, evse_hold_soc) == final.reserve` for the case `evse_hold_soc < reserve_floor`.
- **Verify (EV audit §5 — arbitrage-handoff regression-prone seam):** an inclement hold arriving mid-arbitrage-charge releases `_paused_by_arbitrage` within one tick (no orphan). Behavioral test: prime `_paused_by_arbitrage` with one EV, force `determine_mode` to return a hold next tick, assert `determine_arbitrage_actions(arbitrage_charging=False)` runs in the same dispatch (`energy.py:3106–3113`) and the EV is released from the set, not orphaned. This is the regression-prone transition.
- **Test:** `tests/test_battery_inclement_precedence.py` covers the 27-cell matrix subset that actually changes behavior.
- **Test:** `::test_grid_disconnect_wins_over_warn_hold`.
- **Test:** `::test_full_hold_equivalent_to_pre_v_storm_branch_for_warn_tier`.
- **Test:** `::test_allow_discharge_byte_identical_to_no_storm_path`.
- **Test:** `::test_partial_hold_floor_is_50_pct_by_default`.
- **Test:** `::test_off_peak_watch_skips_surplus_projection_FIN3`.
- **Test (EV audit §2):** `::test_evse_battery_hold_cannot_lower_partial_hold_reserve_floor`.
- **Test (EV audit §2):** `::test_evse_battery_hold_cannot_downgrade_full_hold_backup_mode`.
- **Test (EV audit §5):** `::test_inclement_hold_releases_paused_by_arbitrage_within_one_tick`.
- **Live (headline correctness + beats Enphase):** During current LIVE Flood Watch (Severity=Severe, Certainty=Possible, Event="Flood Watch") → Event fails the outage-relevance gate → `inclement_tier=notice`, `hold_depth=allow_discharge`. Battery discharges normally through mid_peak and peak. Enphase Storm Guard would have held; URA does not. **This is the proof point.**

### D6 — Observability surfaces

Reuse `sensor.ura_energy_battery_coordinator_battery_mode` `extra_state_attributes` — add:
- `storm_forecast: bool` (back-compat) = `decision.hold_depth != "allow_discharge"`
- `inclement_hold_depth: str`
- `inclement_tier: str`
- `inclement_source: str`
- `active_alert_event: str | None`
- `inclement_gated_out_events: list[str]` — Event names that failed the outage-relevance gate (debug aid; explains why a high-severity alert did NOT hold)
- `inclement_expires_at: str | None` (ISO)
- `inclement_grid_precharge: bool`
- `inclement_reserve_floor: int` (default 50 under partial_hold)
- `inclement_reason: str`
- `inclement_solar_horizon: dict` (recoverable, surplus_pct_to_window, permitted_discharge_pct, margin_pct, tomorrow_class, minutes_to_sunset, minutes_to_risk_window_end, reason)

**NEW signal** `SIGNAL_INCLEMENT_STATE_CHANGED` dispatched on transitions of `(tier, hold_depth)`. Verify no equivalent exists before adding.

**Deferred:** dedicated `sensor.ura_inclement_state` entity — attribute pack on battery_mode suffices for v1.

### D7 — Live Validation plan (Review D)

Live Flood-Watch is the natural fixture for the **headline correctness test**.

| # | Acceptance criterion | How to verify |
|---|---|---|
| L1 | NWS sensor parsed cleanly | Attrs `active_alert_event` populated; `inclement_gated_out_events` contains "Flood Watch" |
| L2 | **Headline correctness: Flood Watch fails the gate → NOTICE → battery does NOT hold** | Attrs `inclement_tier=notice`, `hold_depth=allow_discharge`; `recorder` shows battery discharged normally through both mid_peak and peak. This is the "beats Enphase" proof. |
| L3 | Reserve_floor unchanged from baseline `self.reserve_soc` during the Flood Watch | Attr `inclement_reserve_floor` equals `reserve_soc` — confirms the gate-out path bypasses the floor elevation logic |
| L4 | Expiry honored if a holding event ever arrives | At Ends timestamp, `inclement_tier` drops to `none`, `hold_depth=allow_discharge` within one tick — no stale lock |
| L5 | Solar-horizon (SURPLUS-based) visible | `inclement_solar_horizon.surplus_pct_to_window`, `.permitted_discharge_pct`, `.margin_pct`, `.minutes_to_sunset` populated and plausible during mid_peak/peak; `recoverable=None`, `reason="off_peak_skip"` during off_peak (FIN-3) |
| L6 | Multi-provider election healthy | Dynamic Weather HEALTHY post-D0; `binary_sensor.ura_weather_divergence` stable |
| L7 | Pre-charge gating | With `GRID_PRECHARGE_ON_HOLD=False` (default), no grid pre-charge events triggered by inclement — verified via recorder |
| L8 | No precedence regression | 24h post-deploy `battery_mode` history shows no unexpected `backup` and no skipped peak-discharge on clear days |
| L9 | Condition-only fallback (optional) | Temporarily clear `CONF_INCLEMENT_NWS_ALERTS_ENTITY`, restart, verify off_peak partial_hold fires only if ≥2 providers stormy |
| L10 | Partial-hold floor is 50% (FIN-1) | If any partial_hold ever fires during validation window, recorder shows discharge stops at SOC=50% (not 40%) |
| L11 | EVs not orphaned on hold transition (EV audit §5) | Trip a hold while an arbitrage-charge EV is paused; recorder shows `_paused_by_arbitrage` cleared within one tick and the EV resumed |

Post-restart README write-back (per CLAUDE.md mandate) is required to close the cycle.

### D8 — Test authority (Reviewer C focus)

NWS fixtures derive from a **single canonical fixture** captured from the operator's live sensor. Behavioral tests drive `EnergyBatteryCoordinator.determine_mode()` end-to-end. No hand-authored alert dicts inline (Bug Class C5 from v4.6.3).

---

## Tier classification

**Tier 2-DB** — elevated unambiguously now. This cycle:
- Modifies the peak / mid_peak / off_peak discharge branches directly (cost-impacting arbitrage logic).
- Threads a new `effective_reserve` through 4 TOU result sites.
- Modifies the `determine_mode` precedence comment block — the same block v4.5.0 D5 explicitly warned against silent reorderings.
- Cross-coordinator ripple risk: `SIGNAL_INCLEMENT_STATE_CHANGED` future-couples HVAC/EV/NM.
- Regression-prone — failure mode is either (a) battery never discharges during a stale alert (Enphase-style lock) or (b) battery discharges through a real storm.
- **FIN-2 reuses `_expected_solar_surplus_pct` — a v5.3.8 attainability primitive on which the existing arbitrage / ATTAIN paths already depend. Mis-wiring it risks silent over- or under-reading of recoverability.**
- **EV/EVSE audit clean (2026-06-15) — but the 5 audit findings extend reviewer framings A and B** (see audit section above and framings below).

Three framing-disjoint reviews:
- **Reviewer A — Detection + fusion + matrix correctness, AND surplus-reuse correctness AND arbitrage-handoff seam.** Outage-relevance gate is first and load-bearing; tier/TOU/solar-horizon matrix; certainty/severity ordering; product-type folding; watch corroboration; expiry/no-stale-lock; no spurious hold under malformed sensors; condition-only fallback fail-mode; case-insensitive keyword match; timezone handling on Onset/Expires; cross-check majority math; `Status != Actual` filter; **partial_hold reserve-floor arithmetic correct at the boundary** (`max(self.reserve_soc, floor)`) with **floor=50% default per FIN-1**; the "Severity ≥ minimum never overrides the Event-type gate" invariant; **FIN-2 reuse: verify `SolarHorizon` calls `_expected_solar_surplus_pct(now, mins_to_window)` correctly (not raw `solcast_remaining`); verify `permitted_discharge_pct` uses the SAME floor that partial_hold actually applies (no skew between the recoverability check and the rung that consumes it); verify the margin is ADDED (surplus ≥ permitted + margin), not subtracted; verify FIN-3 short-circuit: off_peak callers do NOT instantiate a surplus call; verify the overnight-fallback gate (`classify_tomorrow_solar() in {fair, good}` AND `Expires < tomorrow_sunrise + 2h`) is rung-gated too (off_peak skips it).** **EV audit §5 — arbitrage-handoff seam:** verify the `inclement-hold → pause_requested=False → release _paused_by_arbitrage` transition fires within one tick (`energy.py:3106–3113`); no EV orphaned.
- **Reviewer B — `determine_mode` integration + restart resilience + precedence + cross-coordinator + EV/breaker safety.** `full_hold` short-circuits identically to today's storm branch; `allow_discharge` byte-identical to no-storm path; `partial_hold` doesn't accidentally suppress arbitrage CHARGE in off_peak; per-tick caching no stale-decision window; signal dispatch no double-fire; back-compat of `storm_forecast` key for any external NM/automation consumers (grep first); coordinator restart re-derives decision; no untracked tasks (Bug Class #19); no async_listen unsub leaks (Bug Class #38). **Particular focus: the 4 TOU result sites threading `effective_reserve` — drift between the 4 sites is the most likely regression. Also: confirm the v5.3.8 ATTAIN path's own use of `_expected_solar_surplus_pct` is unaffected (no shared mutable state introduced).** **EV audit §2 — `_apply_evse_battery_hold` precedence:** verify the post-`determine_mode` invocation at `energy.py:2530` is `max()`-safe and can NEVER LOWER a `full_hold` / `partial_hold` `reserve_floor`; the EV hold can only RAISE the reserve, and must not downgrade `BATTERY_MODE_BACKUP` returned by full_hold. **EV audit §3 — breaker chokepoint:** with default `GRID_PRECHARGE_ON_HOLD=False`, confirm the inclement branch's `charge_from_grid=False` does NOT enter the breaker invariant at `energy.py:2615–2616, :2959` and the off-peak ensure-on guard is unaffected. **CONDITIONAL — precharge-ON case:** if precharge is ever enabled, verify the storm `charge_from_grid=True` interaction with the breaker invariant is safe (audit notes this as a future-conditional, not a v1 blocker). **EV audit §4 — pause-ownership:** confirm this cycle writes NO `_paused_by_*` set (grep diff vs `energy_pool.py:196–272`).
- **Reviewer C — Config surface + NWS-sensor parsing + test authority + parsimony.** Options-flow round-trip + restore-from-options for all 7 knobs; default-application for existing installs; **`CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR` default ships as 50, not 40; the 3 Advanced knobs render under an explicit "Advanced" subsection per FIN-1; `CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT` replaces the deleted `CONF_INCLEMENT_RECOVERABLE_KWH_TODAY` (units = %SOC margin, default 5)**; the `CONF_INCLEMENT_POWER_THREAT_EVENTS` default list ships exactly as specified and round-trips through options without mangling; defensive parsing of `attributes.Alerts`; operator parsimony pass; canonical fixture; behavioral tests drive production paths (Bug Class C5); no enum/literal mismatches between policy CONF and `AlertClassification.tier` / `InclementDecision.hold_depth` (Bug Class #22); helper text explicitly explains that fire is notice-only-by-default + addable, and that Severity is NOT the gate (per `feedback_configurability_clarity.md`); helper text on RECOVERABLE_SURPLUS_MARGIN_PCT explains it's a margin over a load-net surplus, not a raw kWh threshold.

**Pre-deploy snapshot required:** 24h pre-deploy `battery_mode` state distribution + `reserve_level` distribution by TOU period, so post-deploy ±25% comparison is meaningful.

---

## Files expected to change

- `custom_components/universal_room_automation/domain_coordinators/inclement.py` — **NEW** (AlertClassifier + SolarHorizon + InclementFusion). `SolarHorizon` calls into `battery._expected_solar_surplus_pct` + `battery.classify_tomorrow_solar` per FIN-2.
- `custom_components/universal_room_automation/domain_coordinators/weather_manager.py` — extend with `current_storm_condition()`.
- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — replace storm branch at `:2447–2464`; refactor TOU sites at `:2474, 2481, 2562, 2577` to read `effective_reserve`; expand attrs at `:2895`; update precedence comment at `:2418–2440`; delete `has_storm_forecast()` at `:648–659`. **`_expected_solar_surplus_pct` at `:1362` is unchanged — only re-used by inclement.py.**
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — add `CONF_INCLEMENT_*` + defaults (including the default `POWER_THREAT_EVENTS` list, `PARTIAL_HOLD_RESERVE_FLOOR=50`, `RECOVERABLE_SURPLUS_MARGIN_PCT=5`).
- `custom_components/universal_room_automation/domain_coordinators/signals.py` — add `SIGNAL_INCLEMENT_STATE_CHANGED`.
- `custom_components/universal_room_automation/config_flow.py` — extend weather step; group 3 Advanced knobs under "Advanced" subsection (FIN-1).
- `custom_components/universal_room_automation/translations/en.json` + `strings.json` — labels + helper text (including "Advanced" section label).
- `quality/tests/test_inclement_alert_classifier.py` — NEW.
- `quality/tests/test_inclement_solar_horizon.py` — NEW (includes FIN-2 surplus-reuse tests + FIN-3 off_peak short-circuit test).
- `quality/tests/test_battery_inclement_precedence.py` — NEW (includes EV-audit-§2 `_apply_evse_battery_hold` precedence tests + EV-audit-§5 arbitrage-handoff release-on-hold test).

**Files NOT changed (confirmed by EV/EVSE audit):**
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — `_apply_evse_battery_hold` (:2453), EV drain pause (:2671), breaker invariant (:2615, :2959), post-decision arbitrage dispatch (:3106) all read-only relative to this cycle. NO edits.
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py` — 6 `_paused_by_*` sets (:196–272), resume-handoff chains (:559, :755, :849), EV TOU pause (:459) all read-only relative to this cycle. NO edits. NO new `_paused_by_storm` set is added (explicit non-goal).

---

## Plan completion tracking (mandatory)

Possibly deferred post-build:
- Dedicated `sensor.ura_inclement_state` entity (attribute pack sufficient v1).
- Broader condition set tunable later (hardcoded in v1).
- HVAC / EV consumers of `SIGNAL_INCLEMENT_STATE_CHANGED` (signal ships; consumers future).
- Multi-line `CONF_INCLEMENT_POWER_THREAT_EVENTS` editing UX — if options-flow text input proves clumsy, swap to a tag-style selector in v2.
- `CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION` UI re-exposure — currently hardcoded True; cheap to surface as a primary toggle later.

**Explicit NON-GOALS (this cycle):**
- **EV battery-drain threshold is NOT storm-tightened** (audit §1; operator decision 2026-06-15 "simpler is good"). Rely on existing `_apply_evse_battery_hold` (`energy.py:2453`) for charging-EV backup protection. The EV drain pause (`energy.py:2671`) reads the STATIC `self._battery.reserve_soc` (`:174`); the storm-elevated commanded reserve does NOT thread there, and that is by design.
- **Storms do NOT pause EVs in this cycle** (audit §4). `_apply_evse_battery_hold` + grid-serves-EV already protect the reserve during a charging EV. **Guardrail for any FUTURE revision that wants storm-paused EVs:** it MUST add a dedicated `_paused_by_storm` set with explicit precedence in the resume-handoff chains (`energy_pool.py:559–563, 755–759, 849–853`) — NEVER reuse an existing pause set (the #15/#16 collision-class lesson).

---

# SUMMARY

## LOAD-BEARING DECISIONS (FIN-1 / FIN-2 / FIN-3 + EV-audit applied — locked)

1. **D-A: Event-type OUTAGE-RELEVANCE is the PRIMARY classifier gate.** Severity, Certainty, and product-type (Watch/Warning) name are NOT sufficient — CAP defines them as independent axes. First gate is "does the Event name match a power-threat keyword?"; on FAIL the alert is `NOTICE` regardless of Severity/Certainty. On PASS the alert proceeds to certainty tiering (Observed/Likely → warn; Possible/Unlikely → watch) with product-type folding (a "Warning" product promotes certainty), then severity as a secondary noise filter. **LOCKED as proposed.**
2. **D-B: `CONF_INCLEMENT_POWER_THREAT_EVENTS` default list = `["Tornado", "Severe Thunderstorm", "Ice Storm", "Winter Storm", "High Wind", "Extreme Wind", "Hurricane", "Blizzard"]`.** Single editable keyword list — simultaneously the outage-relevance gate AND the escalation hook. Case-insensitive substring match. Fire alerts notice-only-by-default; flood alerts never hold this property by default. **LOCKED as proposed.**
3. **D-C: `CONF_INCLEMENT_WARN_MIN_SEVERITY` default = "Severe"** (operator framing: "Severe + likely"). Secondary noise filter applied AFTER the Event-type gate; never overrides the gate. **LOCKED.**
4. **D-D: Hold-depth matrix defaults (tier × TOU × solar horizon) — FIN-3 applied.** Off_peak rows hold readily without consulting recoverability (cheap to hold; no arbitrage forgone). Mid_peak / peak rows consult `SolarHorizon.recoverable`. Warn-tier always holds (recoverability not consulted). **LOCKED as proposed.**
5. **D-E: `CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR` default = 50%** (FIN-1, up from 40%). Advanced subsection. SOC URA preserves during a partial_hold. **LOCKED at 50.**
6. **D-F: SURPLUS-based "recoverable" — FIN-2.** `CONF_INCLEMENT_RECOVERABLE_KWH_TODAY` (raw 8 kWh) is **DELETED**. Replaced by `CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT` default **5 %SOC**. SolarHorizon reuses `_expected_solar_surplus_pct(now, mins_to_window)` at `energy_battery.py:1362` (already nets house load via `SOLAR_CAPTURE_FACTOR=0.5`) and `_should_attain_peak_buffer` caller pattern at `energy_battery.py:1587, 1660`. Recoverable iff `surplus_pct >= permitted_discharge_pct + margin`. Structurally raises the bar vs raw-kWh; cloudy/high-load days cannot falsely read recoverable. **LOCKED.**
7. **D-G: Overnight-recoverable fallback is RUNG-GATED (FIN-3).** Only consulted for mid_peak / peak rungs. Off_peak skips both today-recoverability AND the overnight fallback (off_peak holds readily regardless). For mid_peak / peak: fallback is `classify_tomorrow_solar() in {fair, good}` AND alert `Expires < tomorrow_sunrise + 2h`. **LOCKED.**
8. **D-H: `CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION = True` (hardcoded; not exposed in v1 surface).** A passed-gate low-certainty alert requires ≥1 healthy provider to also report stormy before holding. Confirmed toggle: **ON**. **LOCKED.**
9. **D-I: `CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD = False`** (Primary surface). Per durable solar-first principle, never burn grid energy to backup-fill on a watch. Confirmed toggle: **OFF**. **LOCKED.**
10. **D-J: `CONF_INCLEMENT_CONDITION_CORROBORATION_MODE = "Majority of healthy providers"`** (Advanced subsection). Confirmed toggle: **Majority**. **LOCKED.**
11. **D-K: Hold DURATION = alert's own `min(Ends, Expires)` ONLY.** No fixed timer anywhere. Condition-only path persists while ≥2 providers stormy + `CONDITION_DECAY_MINUTES=30` decay. **LOCKED.**
12. **D-L: Fail-mode when NWS sensor unavailable = degrade to condition-only path** (≥2 healthy providers stormy → off_peak partial_hold; mid_peak/peak allow_discharge). **LOCKED.**
13. **D-M: Replace `has_storm_forecast()` fully.** `storm_forecast` attr key kept for back-compat. **LOCKED.**
14. **D-N: 7 knobs total, 4 Primary + 3 Advanced (FIN-1).** Advanced: `PARTIAL_HOLD_RESERVE_FLOOR`, `RECOVERABLE_SURPLUS_MARGIN_PCT`, `CONDITION_CORROBORATION_MODE`. Primary: `NWS_ALERTS_ENTITY`, `POWER_THREAT_EVENTS`, `WARN_MIN_SEVERITY`, `GRID_PRECHARGE_ON_HOLD`. **LOCKED.**
15. **D-O: EV drain protection is NOT storm-tightened — operator-decided, simpler.** The storm-elevated commanded reserve is intentionally NOT threaded into the EV battery-drain comparison at `energy.py:2671–2672`. Charging-EV backup protection relies on the existing `_apply_evse_battery_hold` at `energy.py:2453–2470` (invoked post-`determine_mode` at `:2530`). This cycle does NOT pause EVs during storms and writes NO `_paused_by_*` set. Future revisions wanting storm-paused EVs must add a dedicated `_paused_by_storm` set with explicit precedence in the resume-handoff chains (`energy_pool.py:559–563, 755–759, 849–853`) — never reuse an existing set (#15/#16 collision-class lesson). **LOCKED as NON-GOAL.**

## WHAT CHANGED IN THIS REVISION (FIN-1 / FIN-2 / FIN-3 + EV/EVSE audit fold-in)

- **FIN-1 — Partial-hold floor 40 → 50% + Advanced subsection.** `CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR` default raised to 50 (stronger overnight backup posture; still allows some peak savings). Knob grouped under an "Advanced" subsection in the config-flow step alongside `RECOVERABLE_SURPLUS_MARGIN_PCT` and `CONDITION_CORROBORATION_MODE`. Operator chose expose-all over hardcoding — Advanced grouping is the parsimony lever, not deletion. New live acceptance L10 verifies partial_hold actually stops at 50% if it fires.
- **FIN-2 — Recoverable is now SURPLUS-based, not raw-kWh.** `CONF_INCLEMENT_RECOVERABLE_KWH_TODAY = 8 kWh` is **DELETED**. The v5.3.8 attainability machinery is reused: `SolarHorizon` calls `EnergyBatteryCoordinator._expected_solar_surplus_pct(now, mins_to_window)` (energy_battery.py:1362) — which already nets house load via `SOLAR_CAPTURE_FACTOR=0.5` over a Solcast-overlap-pro-rated window. The caller pattern follows `_should_attain_peak_buffer` (energy_battery.py:1587, 1660). New criterion: `recoverable = surplus_pct >= permitted_discharge_pct + CONF_INCLEMENT_RECOVERABLE_SURPLUS_MARGIN_PCT` (default 5 %SOC margin). This structurally beats the prior raw-kWh threshold for cloudy/high-load days (the v5.3.8 attainability lesson #16 applied). Reviewer A's charge expanded to verify the reuse is wired correctly (correct helper, correct window, margin added not subtracted, no re-introduction of raw-solar over-estimation).
- **FIN-3 — Overnight-recoverable fallback is RUNG-GATED.** `SolarHorizon.recoverable` is only computed when the caller is `mid_peak` or `peak`. Off_peak callers short-circuit to `recoverable=None / reason="off_peak_skip"` — recoverability is irrelevant during off_peak (holding forgoes no arbitrage discharge revenue; cheap to hold). Matrix updated: off_peak rows now read "n/a (off_peak)" in the recoverable column and resolve to full_hold (warn / watch-corroborated) or partial_hold (watch-uncorroborated / condition-only) directly. Mid_peak / peak rows are the only rows that consult the SURPLUS projection. The `InclementFusion.decide()` flow defers SolarHorizon instantiation until after the (tier, tou_period) is known — for off_peak / warn paths, the surplus call is never made.
- **EV/EVSE audit fold-in (2026-06-15) — clean bill of health.** New "EV / EVSE interaction audit" section documents the 5 cross-coordinator findings. (1) EV drain protection intentionally NOT storm-tightened — operator-decided NON-GOAL recorded as D-O. (2) `_apply_evse_battery_hold` precedence threaded as a Reviewer-B acceptance + unit tests in D5. (3) Breaker chokepoint clean with default precharge OFF; conditional precharge-ON case added to Reviewer B framing. (4) Pause-ownership guardrail confirmed (no `_paused_by_*` writes) + explicit NON-GOAL + future-revision guardrail recorded. (5) Arbitrage-handoff release-on-hold seam threaded as a Reviewer-A acceptance + behavioral test in D5 + new live criterion L11. Files-NOT-changed list added under "Files expected to change". D-O added to LOAD-BEARING DECISIONS.
- **Knob table reshaped** into Primary (4) + Advanced (3) subsections per FIN-1. `RECOVERABLE_KWH_TODAY` row removed; `RECOVERABLE_SURPLUS_MARGIN_PCT` row added with explicit helper text explaining it's a margin over a load-net surplus.
- **Confirmed 4 toggles** per operator: watch-corroboration ON, grid-precharge OFF, warn-min-severity "Severe" (operator's "Severe + likely"), condition cross-check "Majority of healthy providers".
- **Attainability helper file:lines re-verified** for FIN-2: `_expected_solar_surplus_pct` at `energy_battery.py:1362`; `_should_attain_peak_buffer` at `energy_battery.py:1587`; caller pattern using both at `energy_battery.py:1660`. Confirmed `SOLAR_CAPTURE_FACTOR=0.5` is the load-netting mechanism.
- **Tier 2-DB retained + 3 framings retained.** Reviewer A's charge explicitly extended to verify the surplus-based recoverable reuse (FIN-2) AND the EV-audit-§5 arbitrage-handoff seam. Reviewer B's charge extended to confirm the v5.3.8 ATTAIN path is unaffected, the EV-audit-§2 `_apply_evse_battery_hold` precedence is `max()`-safe, and the EV-audit-§3 breaker chokepoint is unentered with default precharge OFF (conditional ON case noted). Reviewer C's charge extended to verify the Advanced subsection layout, the deletion of the kWh knob, and the new SURPLUS_MARGIN knob's helper text.

**Plan is FINAL. Build-ready.**
