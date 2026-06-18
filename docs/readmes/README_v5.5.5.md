# URA v5.5.5 — EVSE day/night-aware fill-priority release (EVs charge overnight)

Fixes "good at pausing, bad at starting": EVs never completed a charge because fill-priority held them whenever `forecast_healthy` (= `solcast_remaining ≥ 5 kWh`) was true — and `solcast_remaining` ("remaining today") rolls to the full next-day forecast after midnight, so it was high all night → permanent 24/7 hold. Now the day/night phase is **TIME-anchored** (TOU + day-boundary lookahead, never instantaneous PV), so fill-priority is daytime peak-protection only and releases for the off_peak night window.

## What ships (Tier 3)
- **D1 — fill-priority releases post-peak/off_peak.** Mirrors the battery strategy: `peak` & `off_peak` → release (inert); `mid_peak` → hold ONLY if `peak_ahead_before_offpeak(now)` (a real peak still ahead to protect). The 80% daytime fill target is unchanged. Phase uses ONLY `tou_period` + `peak_ahead` — no solar input → a cloudy/rainy daytime (PV≈0) still correctly HOLDS (not mistaken for night).
- **D2 — battery-drain stays the reserve-gated guarantor; only its high-SOC release is solar-gated.** `battery_out_of_capacity` (release at `SOC ≤ reserve+2`) is untouched — that's the "wait until the battery drains to reserve, then the EV charges from guaranteed grid" mechanism (grid can't be source-tagged; reserve is the only guarantee). The `soc_recovered` (≥85%) release now requires solar actively replenishing (`expected_solar_surplus_now_pct(now) > 1%` — the daylight-windowed FIN-2 primitive, ~0 at night — OR `battery_power > +100W`), so a high-SOC battery is never drained into the car at night (spares L2-rate wear).
- **Overnight rhythm:** day = fill battery / protect peak (EVs held); post-peak = battery drains into the house to reserve; at reserve = EVs charge from guaranteed off_peak grid. Serialized cleanly behind any arbitrage battery grid-charge for breaker safety (20 kW battery + 7.4 kW EV can't run together).

## Review — Tier 3 (4 framing-disjoint)
A (release + phase invariant) APPROVE, B (drain + never-discharge-into-EV invariant) SHIP, C (test authority — D1/D2 mutations *executed*: D1 revert → 9 fails, D2 night-85 revert → fails) PASS, D (completeness — re-enumerated every `_paused_by_*` owner: none still blocks overnight; load-shed clears off-peak, arbitrage-breaker serializes not deadlocks) PASS. 0 CRIT/HIGH/MED; the one LOW (A-L1 `peak_ahead` None-coercion) fixed in-cycle. Mutation-anchored incl. cross-midnight (no rollover re-lock) + cloudy-daytime (TIME-not-PV). Ledgers: `docs/reviews/code-review/v5.5.5_evse_review*`.

---

## Shipwatch acceptance hypotheses (state oracle: HA recorder)

**Immediate (post-restart, daytime — no-regression):**
- **H1 — daytime fill protection intact.** During `peak`/`mid_peak` with battery SOC < 80% AND a peak ahead, the EVSEs remain held. Signal: `sensor.ura_energy_coordinator_ev_charging_status` attr `paused_by_fill_priority` is NON-empty during the next peak/mid_peak window today. Verdict: violated if EVs charge during peak/mid_peak with SOC<80 + peak-ahead. Window: today daytime.

**Delayed (overnight off_peak — the headline):**
- **H2 — fill-priority releases overnight.** During `off_peak` (tou_period == off_peak), `paused_by_fill_priority` is **empty** for the duration. Signal: `sensor.ura_energy_coordinator_ev_charging_status` attr `paused_by_fill_priority == []` while `sensor.ura_energy_coordinator_tou_period == off_peak`. Verdict: violated if non-empty through off_peak (the original 24/7-hold bug). Window: next off_peak (≈20:00→14:00 next day, summer); `alert_if_violated_after: 12h`.
- **H3 — the EVs actually charge overnight.** At least one EVSE (`switch.garage_a` or `switch.garage_b`, or an L1 Moes socket) is `on` for a sustained session (≥30 min cumulative) during `off_peak`. Signal: charger switch state `on` overlapping `tou_period == off_peak`. Verdict: confirmed on a real session; pending until off_peak; violated if zero charging across the full off_peak window with a connected EV. Window: next off_peak.
- **H4 — guaranteed grid, battery not drained into the cars.** During the overnight EVSE charge, the home battery SOC does not fall below its reserve because of the EV (the EV draws grid, not battery). Signal: `sensor.envoy_482543015950_battery` stays ≥ `sensor.envoy_482543015950_reserve_battery_level` throughout any off_peak EVSE-on window. Verdict: violated if battery drops below reserve while an EVSE is charging in off_peak. Window: next off_peak.

**Note for the watcher:** H3 may legitimately be *serialized* behind an arbitrage battery grid-charge on a poor-solar-tomorrow night (the EV starts after the battery reaches `peak_buffer_target`) — confirm via `attain_state`/`arbitrage_phase`, not just `paused_by_fill_priority`. A delay due to arbitrage is NOT a violation.

## Live Validation — PROSPECTIVE (write back after tonight's off_peak)
| # | Criterion | How |
|---|---|---|
| L1 | Deploy healthy | v5.5.5 HACS-installed, config loaded, zero new URA errors |
| L2 | Daytime no-regression (H1) | post-restart now: EVs held during peak/mid_peak with SOC<80 (fill still protects the day) |
| L3 | Overnight release (H2) | tonight: `paused_by_fill_priority == []` through off_peak |
| L4 | EVs charge (H3) | tonight→morning: a real charging session in off_peak; cars meaningfully charged by ~06:00 |
| L5 | Grid-guaranteed (H4) | battery stays ≥ reserve during the off_peak EV charge |
