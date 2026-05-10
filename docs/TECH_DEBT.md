# Tech Debt Register

Living document. Each entry: where the shortcut is, why it's acceptable for now, what would trigger revisiting.

---

## v4.5.11 — AC ramp-down: rough kWh-avoided estimate

**Where:** `OverrideArrester._evaluate_nudge_outcome` and `database.get_ac_ramp_kwh_avoided` (planned for slice 2 D8 sensor).

**Shortcut:** kWh-avoided is computed as `max(0, kwh_before - kwh_after) × min(30, remaining_overshoot_minutes) / 60`. The 30-min projection cap is a sanity bound, not a precision instrument. Not baseline-matched against a comparable-weather-day counterfactual.

**Why acceptable:**
- Conservative bias is correct direction (better to under-claim than over-claim).
- Trend direction (month-over-month) is what users care about for "is the feature working", not absolute kWh accuracy.
- True baseline-matched analytics need Span historical data + comparable-day matching — meaningful complexity for marginal accuracy gain.

**Revisit trigger:** if Span integration exposes a historical API that lets us pull "matched-weather day" energy curves, switch to baseline-difference math. Or if user complains that the kWh-avoided number disagrees with their utility bill.

**Surfaces:**
- `sensor.ura_hvac_ac_kwh_avoided_today` (slice 2)
- `sensor.ura_hvac_ac_kwh_avoided_total` (slice 2)
- Documented caveat in HC user manual (slice 2)
