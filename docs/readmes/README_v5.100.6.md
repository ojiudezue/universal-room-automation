# v5.100.6 — Carrier (cloud-only) stale-detect → bounded ha_carrier reload

**Type:** Feature cycle (HVAC resilience). **Tier:** 2-DB — 3 framing-disjoint reviews + a fix-up
round + orchestrator mutation-verify of the safety-critical sites. Card: `CARRIER-STALE-POLL-REFRESH-1`
(subsumes the restore-fail-tail response). Plan: `docs/planning/PLANNING_carrier_stale_reload.md`.

## Why
The Carrier thermostat integration (`ha_carrier`) is cloud-only and periodically goes stale — it
reports `hvac_action=idle` while the compressor draws kW, restores silently no-op, and only a
config-entry RELOAD refreshes it (operator-observed). This adds automatic detect → bounded reload,
modeled on the Envoy staleness machinery but simpler (cloud-only → no local/cloud reconciliation).

## What shipped
- **D1 detect:** per HVAC tick, a Carrier climate entity is stale if `last_reported` age >
  `CONF_HVAC_CARRIER_STALE_MAX_AGE_S` (900s) and not unavailable, optionally AND-gated by SPAN-kW
  blind-corroboration (idle-but-drawing-kW) — with strict unit refusal (kWh/blank/unknown are NOT
  assumed kW; A2 fix).
- **D2 reload:** bounded reload of the `ha_carrier` config entry only. Guards (first-fail): kill-switch
  (`CONF_HVAC_CARRIER_RELOAD_COOLDOWN_S=0`), suppress-for-day, per-day cap (`=4`), cooldown (1800s),
  per-entry lock, single-entry resolution, and a **SAFETY INVARIANT that aborts if the resolved entry
  is URA's own** (never the parent — watchdog hazard). Plus an **in-flight fence**: skip the reload if
  an AC-ramp nudge / ac_reset / excursion restore is in flight (C-CRITICAL-1 — a reload mid-restore
  would strand a bumped+latched thermostat and delete its recovery record).
- **D3 trip-wire:** **time-based** post-reload settle (`CONF_HVAC_CARRIER_POST_RELOAD_SETTLE_S=1800`),
  scoped to *qualifying* staleness; if still stale after settle → NM-high "reload ineffective" + suppress
  for the day. Plus an **age-only staleness NM** (once/day) independent of the reload path, so a stale
  Carrier that can't be corroborated/reloaded is never silent.
- **Diagnostic:** `sensor.ura_hvac_carrier_freshness` (per-zone age/stale/span-unreadable snapshot).
- **D4:** subsumption query for `HVAC-GOVERNED-RESTORE-FAIL-TAIL-1` corrected to include
  `restore_ok IS NULL AND settled_reason='entity_missing_at_settle'` (reload-induced failures land as
  NULL, not 0). Do NOT auto-close the tail card on it.

## Review outcome (the battery earned its keep)
3 framing-disjoint reviews found **1 CRITICAL + 6 HIGH**: the in-flight-restore strand (C-CRIT-1), a
D3 trip-wire broken 4 ways (tick-vs-time grace, grace<cooldown dead config, permanent latch on
non-qualifying zones), a kWh-unit reload-storm, TWO **hollow test anchors** (the wire-in call site and
the never-reload-parent guard both stayed green on neuter), a blind D4 query, and a silent-stranding
hole. All fixed; the fix-up added 12 real mutation-anchored tests (23 total). **Orchestrator
independently re-mutated the two safety sites** (parent-reload guard, in-flight fence) → both RED on
neuter, restored, 23/23 green.

## Live validation — acceptance criteria (discriminating)
- **L1:** restart clean, config valid, zero new URA errors.
- **L2 (never the parent):** any reload issued targets the `ha_carrier` entry only; NM logs the entry_id.
- **L3 (bounded):** at most 4 reloads/day; a healthy day = 0; hitting the cap fires the trip-wire, not a 5th reload.
- **L4 (in-flight safe):** no reload issued while an AC-ramp nudge/excursion restore is in flight.
- **L5:** `sensor.ura_hvac_carrier_freshness` populates per-zone ages; a genuine stale episode produces either a reload (corroborated) or the age-only NM (uncorroborated).

## Validated 2026-09-09 (post-restart, v5.100.6 live)

| Criterion | Result | Evidence |
|---|---|---|
| L1 clean boot / version | **PASS** | `const.py`=v5.100.6; URA loaded; error_log shows only pre-existing WARNINGs (loader-not-tested, occupancy dedup, boot DB-slow, census/SPAN) — **no new ERRORs** from the Carrier cycle. |
| L5 diagnostic sensor live | **PASS** | `sensor.ura_hvac_coordinator_hvac_carrier_freshness` = 36.7 (worst-zone last_reported age, seconds) — per-zone freshness snapshot populating. |
| L2 never-parent / L3 bounded / L4 in-flight-safe | **organic** | Require a real Carrier stale episode. Disposition = one-shot query: exactly one 'reload ha_carrier' targeting the ha_carrier entry (never URA), ≤4/day, none while a nudge/excursion restore is in flight; OR the age-only NM when uncorroborated. Edge-triggered + orchestrator-mutation-verified in-suite. |

**Rollback not needed.** Orchestrator independently re-mutated the two safety sites (parent-reload guard, in-flight fence) → RED-on-neuter, restored, 23/23 green.
