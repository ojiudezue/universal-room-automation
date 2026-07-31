# URA v5.38.0 — Zone safety-alert split (#12): per-room-type bands, honest safety chip

The Residence-tab red "safety" chips no longer cry wolf: the zone alert previously ORed
four flat comfort literals (85/55/70/25°F/%) over every room — interior rooms legally
drifting past 85°F on summer away-setback lit "safety" alerts with nothing wrong
(verified: Master Suite 87°F bedroom).

## What ships
- `resolve_safety_bands(room_type, hass=None)` + `evaluate_zone_chip(...)` exported from
  safety.py — thin projections over the EXISTING safety tables (OVERHEAT/FREEZE/
  HUMIDITY ladders), one source of truth. The "normal" humidity ladder resolves LIVE
  through the same CM knob the coordinator uses (review A-HIGH-1: operator tuning can
  never drift chip vs coordinator).
- `ZoneSafetyAlertSensor` rewritten: per-room CONF_ROOM_TYPE bands (garage humidity-
  exempt/105 temp; outdoor fully exempt via the zone flag; bathroom transient-tolerant
  snapshot; unknown→generic), leak always-safety (real binary_sensors only, "" falsy),
  MEDIUM+ safety rungs only.
- New attrs: `tripping` [{room, reason}] (+flat lists), `comfort_drift_rooms` (the old
  comfort-grade evaluation — relocated, not lost), `chip_semantics`, `_evaluate_error`.
- Review-hardened: stick-last on eval error (a SAFETY chip never silently reads False
  mid-fault), evaluate-once-per-write snapshot (state/attrs from one snapshot; no double
  scans), outdoor-zone set cached + invalidated on ZM updates, the coordinator's
  outdoor-snapshot twin collapsed to one implementation.
- Parked per plan: tighter infrastructure bands (82-85/60) — follow-up with a
  room_type enum decision.

## Review provenance
Tier 2, two framing-disjoint reviews: 4 HIGH (CM-knob drift; silent-False safety chip;
double-evaluate; snapshot twin) + 5 MED + LOWs — all fixed; infrastructure→generic
adjudicated as plan-ratified. Real by-reference mutation tests added (table edit →
projection follows). 41 zone tests + 105 safety-coordinator tests green; zero new
suite failures.

## Live Validation
- H1: clean boot. H2: on the current away-setback house, Master Suite / Back Hallway
  chips read OFF with the warm rooms listed in `comfort_drift_rooms` (cry-wolf fixed,
  information preserved). H3: a genuine leak still trips with the room named. H4:
  Outside zone exempt (Patio can't trip on a hot day).
