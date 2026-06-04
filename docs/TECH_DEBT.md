# Tech Debt Register

Living document. Each entry: where the shortcut is, why it's acceptable for now, what would trigger revisiting.

---

## Presence — Tier 1 ORs mmWave + PIR into one per-room bool (no signal provenance)

**Where:** `domain_coordinators/presence.py:3281-3282` — Tier 1 occupancy is
`any(getattr(t, "_room_occupied", {}).values())`. `_room_occupied` is a single
per-room boolean; mmWave and PIR contributions are merged upstream and the
coordinator does NOT record which sensor type asserted occupancy. Fan entities
are likewise not visible to the presence layer.

**Shortcut:** treating mmWave and PIR as one undifferentiated "Tier 1" signal.
Cheap, and correct as long as both are equally trustworthy.

**Why acceptable (today):** months of tuning have made the current presence stack
stable; nothing is broken. PIR and mmWave OR'd together gives good coverage. The
operator is explicitly NOT willing to risk presence regressions for a speculative
improvement (2026-06-03).

**Revisit trigger:** fan/pet mmWave false-positives become worth fixing in code
(see `docs/BACKLOG.md` "Fan-noise mmwave mitigation"). Splitting provenance is the
PREREQUISITE for any "discount fan-suspect mmWave but trust PIR" or PIR+mmWave
fusion scheme. **Hard gate before that work:** a CONTEXT-WIDE audit of every
presence path — room, zone, house, AND presence-coordinator — to prove the split
introduces no blind regression. Audit-first; the survey is the deliverable gate.
Likely Tier 2-DB (presence↔HVAC↔compliance↔safety trust-hierarchy ripple).

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
