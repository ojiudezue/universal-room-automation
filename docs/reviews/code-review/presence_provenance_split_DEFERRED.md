# Presence Provenance-Split — Deferred Review Findings

**Cycle:** `feature/presence-provenance-split`
**Pre-review baseline:** `pre-review-presence-provenance-split` at `b7701d5`
**Fix-up pass:** post-Tier-2-DB review (A + B + C); all three returned SHIP, no CRITICAL/HIGH-data findings, one HIGH-test (C-HIGH-1) + four MEDs/LOWs fixed in-cycle per the operator's "fix LOWs in-cycle" rule.

Deferrals below are non-issues or risk-bounded enough to not block deploy.

---

## A.1 — LOW — Derived `_room_occupied` allocates a fresh dict per read

- **Reviewer:** A (data integrity).
- **Site:** `domain_coordinators/presence.py` derived `_room_occupied` `@property` at ~:399-418.
- **Concern:** Each property access constructs a new dict via comprehension. `_derived_mode` reads it inside `_run_inference` per tick per zone (and `to_dict` reads it for diagnostics). Pre-split this was a stored-attribute read.
- **Why deferred:** Observation-only at today's scale (~10 zones x ~3 rooms). The audit helper at `presence.py:313` already snapshots once. No measured tick-budget pressure; no operator complaint. Reviewer A explicitly tagged this "not blocking — can wait until tick-budget pressure emerges."
- **Where tracked:** This deferral note. Revisit if `_run_inference` p95 budget tightens or if zone count grows materially.

## B-LOW-2 — `_classify_entity_kind` picks first-match if duplicate room names exist

- **Reviewer:** B (migration / signal chain).
- **Site:** `domain_coordinators/presence.py:236-256`.
- **Concern:** During a Room ConfigEntry reload, an old entry + new entry can briefly coexist with the same `CONF_ROOM_NAME`. The classifier iterates entries and `break`s on the first match. If the old entry is iterated first, the classifier briefly returns stale sensor-list membership.
- **Why deferred:** Reload windows are seconds, classifier output during that window is consumed only by the live state-change callback whose output rolls through the next inference tick. Reviewer B classified the fix as "deferrable, ~6 LoC" and explicitly tagged "Defer-OK". Steady-state behavior is unaffected.
- **Where tracked:** This deferral note. Bundle with any future hardening of the config-entry reload path if a reload-race incident materializes.

## C-LOW-1 — `binary_sensor.py` D5 attr block silently swallows ALL exceptions

- **Reviewer:** C (new surfaces / test authority).
- **Site:** `binary_sensor.py:437-443`.
- **Concern:** Bare `except Exception:` falls back to all-False defaults without `_LOGGER.debug(..., exc_info=True)`. A future coordinator API rename would silently break the dashboard.
- **Why deferred:** The fix is one-line (`_LOGGER.debug(..., exc_info=True)`) but the surface is the diagnostic-attr extraction, which is intentionally lenient — failure modes here are operator-discoverable via the dashboard reading all-False rather than silent runtime impact. Same applies to C-LOW-2 below.
- **Where tracked:** Bundle this with C-LOW-2 in a single follow-up diagnostic-logging pass if the dashboard starts misbehaving without obvious cause.

## C-LOW-2 — `_zone_provenance_breakdown` / `_signal_consensus_get_list` silently swallow exceptions

- **Reviewer:** C.
- **Site:** `sensor.py:3949-3953`, `sensor.py:3962-3966`.
- **Concern:** Same shape as C-LOW-1 — bare except returns empty/zero without logging.
- **Why deferred:** Same reasoning as C-LOW-1. Lower observability cost than the diagnostic-attr surface because these are zone-rollup helpers a level deeper.
- **Where tracked:** This deferral note; co-fixable with C-LOW-1 in one pass.

---

## Items resolved (not deferred)

For traceability only. Full disposition is captured in the commit message + the three review docs in this directory.

| Finding | Severity | Disposition |
| --- | --- | --- |
| C-HIGH-1 | HIGH | FIXED — regex pins call shape `tracker.update_room_occupancy(room_name, occupied[, kind=...])` with optional trailing comma. |
| C-MED-1 | MED | FIXED — rewrote as source-grep canary against the production `_signal_consensus_inputs = {...}` emit block (option b per reviewer guidance). |
| C-MED-2 | MED | FIXED (doc) — added docstring paragraph in `_compute_fan_interference_rooms` making the off-cadence read explicit. |
| B-MED-1 | MED | FIXED — three comment sites renamed from "Bug Class #1" to "v4.7.18.1 review finding B-HIGH-1". |
| A-LOW-2 | LOW | FIXED — `"tier1"` sentinel bucket added to per-zone breakdown in `presence.py` and `sensor.py`. |
| B-LOW-3 | LOW | FIXED — classifier now merges `{**entry.data, **entry.options}` for entry-type / room-name checks too. |
| B-LOW-1 | LOW | FIXED — seed loop no longer short-circuits on `not occupied`; OFF rooms get an empty provenance dict so Invariant 4 holds for all discovered rooms. `_has_sensors` is already True via `register_entity` at this point, so no observable side-effect on `_derived_mode`. |
