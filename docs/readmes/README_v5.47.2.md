# v5.47.2 — Hotfix: NM Conditioning Switch Resolved via Registry

The v5.47.0 NM severity-conditioning consumer guarded on a hardcoded
`switch.ura_memory_nm_conditioning`; the live entity id is device-name-
derived (`switch.ura_coordinator_manager_memory_nm_conditioning`), so
the guard never matched and — combined with the (correct) B3 boot-gap
rule "absent switch = no conditioning" — the consumer was permanently
inert. Fails-safe, but it is one of the two week-one VALUE-gate criteria,
so it cannot ride.

Fix: resolve the entity id from the entity registry by unique_id
(`universal_room_automation_memory_nm_conditioning`), slug-guess
fallback retained. Third instance of the entity-id-guessing class this
week (fan_veto fused sensor, memory status sensor naming, this) — rule
now firmly established: NEVER hardcode a derived entity id; resolve via
registry unique_id.

Suite: 36 memory tests (drill caught + fixed a loose anchor), full
7966/30 baseline, zero drift.

## Live Validation — prospective
- **Live:** with the switch ON, a high_humidity/high_co2 LOW-or-MEDIUM
  hazard in an allowlist room logs the conditioning breadcrumb
  (dampened or insufficient-history DEBUG) — proves the guard now finds
  the switch.
