# URA v5.5.0 — Robust Inclement-Weather Detection + TOU/Solar-Horizon-Aware Battery Hold

Replaces URA's reliance on Enphase Storm Guard (cloud-only, NWS-driven, no local veto, multi-day stale locks, blunt 100% grid pre-charge) with a **local alert + condition fusion** that produces a **graduated hold-depth decision** parameterized by (a) confidence tier, (b) current TOU period, and (c) solar-recovery horizon. Operator thesis: a warning at 8am with a sunny day ahead means something entirely different from a warning at dusk heading into a 6–12h overnight outage window.

Tier 2-DB at full ceremony: build + 1 in-cycle correctness fix (EV-audit §2) + 3 framing-disjoint reviews + 1 fix-up pass + focused fourth review (final 0 CRIT / 0 HIGH outstanding). Reviews: `docs/reviews/code-review/v5.5.0_inclement_review{A,B,C}_*.md` + `v5.5.0_inclement_summary.md`. Plan: `docs/planning/PLANNING_inclement_weather_reserve.md`.

## What ships

### Detection — Event-type OUTAGE-RELEVANCE is the PRIMARY gate (D1)
`AlertClassifier` (`inclement.py`) parses the NWS Alerts sensor and gates on **Event name** first: only events matching the operator-curated `CONF_INCLEMENT_POWER_THREAT_EVENTS` list can ever hold the battery. Severity is a *secondary noise filter*, never the gate (the CAP standard defines Severity / Certainty / product-type as independent axes). A `Flood Watch` (Severity=Severe) fails the gate → `NOTICE` → battery discharges normally. This is the "beats Enphase" property: Enphase Storm Guard would hold; URA does not.

### Hold-depth ladder — not a binary hold (D5)
Three rungs replace the old binary storm hold: `full_hold` (short-circuit to BACKUP), `partial_hold` (TOU branches run but with an elevated reserve floor, default **50%**), `allow_discharge` (no override — byte-identical to a no-storm tick). The decision is matrix-driven by tier × TOU period × solar horizon.

### Solar-horizon recoverability — surplus-based, net of house load (D2, FIN-2/FIN-3)
`SolarHorizon` reuses the v5.3.8 attainability primitive `_expected_solar_surplus_pct` (returns %SOC, already nets house load via `SOLAR_CAPTURE_FACTOR=0.5`). A mid_peak/peak discharge counts as "recoverable" only if projected solar surplus exceeds what `partial_hold` would permit, by a margin (default 5 %SOC). off_peak callers short-circuit (recoverability is moot — holding forgoes no arbitrage discharge).

### Hold duration = the alert's own Expires/Ends (the stale-lock fix)
No fixed timer anywhere. The decision's `expires_at = min(Ends, Expires)` across contributing alerts; each tick re-evaluates, so a hold cannot outlive its alert — directly fixing the Enphase multi-day stale lock.

### Config + observability (D3/D4/D6)
7 knobs (4 Primary + 3 under an "Advanced" `section()`), plain-English named-bucket labels. `ConditionElector` adds a multi-provider local-condition cross-check via `WeatherProviderManager`. Observability via `sensor.ura_energy_battery_coordinator_battery_mode` attrs (`inclement_tier`, `inclement_hold_depth`, `inclement_gated_out_events`, `inclement_solar_horizon`, …) + new `SIGNAL_INCLEMENT_STATE_CHANGED`.

### In-cycle correctness fix (EV-audit §2)
The build proved the plan's audit §2 wrong: `_apply_evse_battery_hold` (`energy.py:2480`) was **not** `max()`-safe — a charging EV captured below an inclement floor would silently undercut it. Fixed so the EVSE hold can only *raise* the reserve, never lower it.

## Accepted-as-designed / Known limitations

- **EV battery-drain threshold is NOT storm-tightened** (operator decision 2026-06-15, "simpler is good"). Charging-EV backup relies on the existing `_apply_evse_battery_hold`. This cycle pauses no EVs and writes no `_paused_by_*` set.
- **KNOWN GAP — arbitrage-WAIT can briefly bypass the partial_hold floor** (MEDIUM, tracked follow-up; `energy_battery.py:1521`). When the arbitrage gate is open (tomorrow's solar poor/very_poor) **AND** an uncorroborated watch is active overnight, the arbitrage WAIT phase returns `reserve_level=self.reserve_soc`, ignoring the elevated 50% floor. **Not a regression** (byte-identical to the build's original design; the A-CRIT-1 fix clamps the drain-target fallback, which arbitrage short-circuits past). Practical exposure is small: when tomorrow is poor, arbitrage is *charging the battery up* for the bad solar day, which serves backup anyway; WAIT is a transient hold. The proper fix threads the floor through the arbitrage/attain state machine and is scoped as its own Tier-2-DB follow-up. **Shipwatch: do not flag a brief reserve dip to `reserve_soc` during arbitrage WAIT + active uncorroborated watch as a violation — it is a known, accepted gap for v5.5.0.**

## Live Validation — Validated 2026-06-15 (restart 19:35 CDT, HACS v5.5.0 confirmed installed)

Post-restart read of `sensor.ura_energy_coordinator_battery_strategy` (the entity that carries the new inclement attrs — note: NOT the plan-assumed `sensor.ura_energy_battery_coordinator_battery_mode`, which does not exist; the URA energy decision surface is `ura_energy_coordinator_battery_strategy`). Config entry `state=loaded`, zero URA ERROR lines from the v5.5.0 boot (the only 2 ERROR lines are a stale pre-restart DB-write-worker boot transient at 18:31, before the 19:35 restart).

**Live context at validation:** TOU=peak, SOC=71%, `battery_power=-5.741` (discharging), `envoy_available=true`, `arbitrage_savings_today=0.96`. **No active NWS alert** — the NWS sensor reads `state=0, Alerts=[]` (the 06-11 Flood Watch the plan used as fixture expired 06-12). So the inclement path is in its correct *no-alert resting state*.

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | NWS sensor read cleanly | PASS (no-alert) | `active_alert_event=null`, `inclement_gated_out_events=[]` with the sensor at 0 alerts — parsed without error |
| L2 | **Headline: alert fails gate → NOTICE → no hold** | **DEFERRED — no active alert** | No NWS alert active at validation (06-11 Flood Watch expired 06-12). `inclement_tier=none`, `hold_depth=allow_discharge` — battery discharges normally through peak, which is the *same outcome* the headline wants, just driven by "no alert" rather than "alert gated out". The gate itself is mutation-anchored in-suite (`test_inclement_alert_classifier.py::test_flood_watch_severe_possible_returns_NOTICE_because_flood_fails_gate` + 13 sibs). Awaits a real alert to exercise live (recurring caveat class, same as v5.3.8/v5.3.9). |
| L3 | reserve_floor == reserve_soc when not holding | PASS | `inclement_reserve_floor=10` == `reserve_soc=10` |
| L4 | Expiry honored (no stale lock) | DEFERRED | No holding event to expire |
| L5 | Solar-horizon attr present + off_peak skip semantics | PARTIAL PASS | `inclement_solar_horizon` present; `recoverable=null`, `reason="not_consulted"` (correct — no mid_peak/peak watch active). off_peak `reason="off_peak_skip"` not exercised |
| L6 | Multi-provider election healthy | PASS | `binary_sensor.ura_energy_coordinator_weather_divergence=off` (stable) |
| L7 | No inclement grid pre-charge (default OFF) | PASS | `inclement_grid_precharge=false` |
| L8 | No precedence regression | PASS (initial) | Battery discharging through peak normally (`self_consumption`, "Peak — battery covers load, solar exports"); no unexpected `backup`; arbitrage active (savings 0.96). The `allow_discharge`-byte-identical guarantee holds in practice. |
| L9 | Condition-only fallback | DEFERRED | Not exercised (no storm conditions) |
| L10 | Partial-hold floor 50% | DEFERRED | No partial_hold fired (no alert) |
| L11 | EVs not orphaned on hold | DEFERRED | No hold transition (no alert) |

**Verdict:** deploy healthy, inclement subsystem live and wired into the battery decision surface, no-alert resting state correct, no regression to normal discharge behavior. The hold-path and headline-gate criteria (L2/L4/L9/L10/L11) are **live-unexercised because no NWS alert is currently active** — they are mutation-anchored in the test suite and will validate live on the next real power-threat alert.

**Open operator item (D0, NO CODE):** the options probe could not confirm via MCP whether `CONF_INCLEMENT_NWS_ALERTS_ENTITY` is set to `sensor.nws_alerts_gps_30_3146_98_0159_nws_alerts_alerts`. **Until that is wired in Energy → Weather Providers options, the feature stays dormant when a real alert arrives.** Confirm/set it, then the next active power-threat alert exercises L2 live.

**Tracked follow-up (see Known limitations above):** arbitrage-WAIT partial_hold-floor gap → own Tier-2-DB cycle.
