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

## Live Validation — PROSPECTIVE (to be written back post-restart per CLAUDE.md mandate)

The live `Flood Watch` (Severity=Severe, Certainty=Possible) is the natural fixture for the headline correctness proof.

| # | Acceptance criterion | How to verify |
|---|---|---|
| L1 | NWS sensor parsed cleanly | `active_alert_event` populated; `inclement_gated_out_events` contains "Flood Watch" |
| L2 | **Headline: Flood Watch fails the gate → NOTICE → battery does NOT hold** | `inclement_tier=notice`, `hold_depth=allow_discharge`; recorder shows discharge through mid_peak + peak. The "beats Enphase" proof. |
| L3 | reserve_floor unchanged from baseline during the Flood Watch | `inclement_reserve_floor == reserve_soc` |
| L4 | Expiry honored if a holding event arrives | at Ends, `inclement_tier`→`none`, `hold_depth=allow_discharge` within one tick |
| L5 | Solar-horizon (surplus-based) visible | `inclement_solar_horizon.surplus_pct_to_window` etc. populated during mid_peak/peak; `recoverable=None`, `reason="off_peak_skip"` during off_peak |
| L6 | Multi-provider election healthy | Dynamic Weather HEALTHY; `binary_sensor.ura_weather_divergence` stable |
| L7 | Pre-charge gating | default GRID_PRECHARGE_ON_HOLD=False → no grid pre-charge from inclement |
| L8 | No precedence regression | 24h `battery_mode` history: no unexpected `backup`, no skipped peak-discharge on clear days |
| L9 | Condition-only fallback (optional) | clear NWS entity → off_peak partial_hold only if ≥2 providers stormy |
| L10 | Partial-hold floor is 50% | if partial_hold fires, discharge stops at SOC=50% |
| L11 | EVs not orphaned on hold transition | hold trips while an arbitrage-charge EV is paused → `_paused_by_arbitrage` cleared within one tick |

*A cycle is not closed until this section carries the post-restart `Validated <date>` results table.*
