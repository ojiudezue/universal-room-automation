# v5.93.1 — Envoy power-read staleness gating (clean core: solar + drain-HOLD + observability)

**Card:** `ENVOY-PRODUCTION-STALE-1`
**Tier:** 2-DB, elevated to Tier-3 review (2 plan-reviews + 4 framing-disjoint build-reviews + 2 focused re-reviews + 3 fix-ups + orchestrator verify). PATCH — correctness/safety fix.
**Merge:** `feature/envoy-shared-staleness` → develop.

## Problem

Envoy-sourced power reads can freeze at a stale-but-valid number that reads as live — observed: `solar_production` reported **0 kW for ~16.5 h while the house was exporting 6 kW**. URA's solar entity derives from it, and several energy decisions trust the frozen value directly. The existing `envoy_status` "stale" state is connection-level and can't see a single frozen read while the feed is otherwise healthy.

## Solution — gate the READ (scoped to the clean core)

A shared `_state_age_s(state, *, stamp="last_reported")` helper (`last_reported`, not `last_updated`, so a healthy pinned-0 sensor is never false-stale; `max(0.0, …)` clamp) gates the reads, returning `None` → the existing LKG/envelope fallback engages:

- **D3 — solar_production** (the original ask): frozen read → `None` → LKG/envelope; the frozen 0 can no longer suppress a real value.
- **D2 — primary battery_soc → LKG** (bounded, cloud-fallback retains its own gates).
- **D4-D — battery-drain-pause release HOLD** (the safety win): under a stale battery CT, `battery_ok = (not battery_discharging) and not battery_power_unknown` → an existing drain pause is **HELD** across the stale tick instead of being dropped (which would let the EV keep draining a still-discharging house battery). develop's `daytime_release` / `overnight_release` / `must_start_by` split is untouched and still fires on its own conditions; the fresh path is byte-identical.
- **D4-E/F/G** — billing net-power gate, envoy-cache write gated to fresh SOC (ungated power columns dropped), load-shed sustained-window drain on stale.
- **D-OBS** — the existing `sensor.ura_energy_coordinator_envoy_status` gains per-source ages + `stale_sources` / `unconfigured_sources` / `missing_sources` + `stale_reason`, unioned into its stale state (thresholds imported from the `energy_const` knobs; `≤ 0` kill-switch honored on both the gate and the display).

## Scope split (what was DROPPED, and why)

The 4-review Tier-3 pass found the breaker-guard + grid-cap fail-close treatment **over-corrected** — it locked arbitrage charge chunks on a guard that's *disabled by default*, manufactured false over-caps, and could strand the EV — contradicting the v5.17.5 anti-abort precedent. Those were **reverted to develop behavior** and parked as `BREAKER-GRIDCAP-STALE-TELEMETRY-1` for a proper future cycle. **`git diff develop` on the breaker/arbitrage surface is empty.** Separately, **arm-on-unknown** (arming a *new* drain pause under a stale CT) was dropped because it stranded the EV overnight (no nighttime release) — the arming gap is accepted and carded as `ENVOY-DRAIN-ARM-STALE-CT-1` (hardware reserve + CT-recovery are the backstops).

## Reviews

2 plan-reviews (both FIX-REQUIRED → last-reported semantics + missed sites). 4 Tier-3 build-reviews: the initial build shipped a real safety bug (drain release-path DROP) caught by the mutation drill; B+D converged on the breaker/grid-cap over-correction; C found pervasive neuter-deletable anchors. 2 re-reviews after the scope split found + fixed the arm-on-unknown strand and hollow wire-in anchors. 28 anchors; every kept gate mutation-verified RED-on-neuter (drain HOLD, wire-in ×2, producer gates ×3, billing, cache, load-shed, D-OBS kill-switch + classifier). Orchestrator independently verified: 2-line drain change, breaker surface byte-identical, arm-on-unknown removed, no `via_device`, `net_power_w` ungated on the breaker path.

### Acceptance criteria
- **Verify:** a frozen solar/SOC read falls back to LKG/envelope (a healthy pinned-0 sensor is NOT flagged stale — `last_reported` semantics).
- **Verify:** under a stale battery CT, an existing drain pause is HELD; the breaker guard + arbitrage behave byte-identically to develop.
- **Live:** `sensor.ura_energy_coordinator_envoy_status` exposes per-source ages + `stale_sources`; a genuinely frozen source reads stale, a healthy source does not; clean boot, no new URA errors; energy decisions unchanged on fresh telemetry.

## Pre-deploy gate
py_compile clean; no conflict markers; 28 cycle tests; full-suite name-diff vs develop = (recorded below); breaker-surface git-diff empty; 0 via_device.

## Validated 2026-09-03 (post-restart)

| Criterion | Observed evidence | Result |
|---|---|---|
| D-OBS per-source staleness live + correct | `sensor.ura_energy_coordinator_envoy_status` exposes `solar_age_s` / `net_power_age_s` / `battery_power_age_s` / `primary_soc_age_s` — all populated + fresh (~85s, under the 180/300s thresholds); `stale_sources` / `unconfigured_sources` / `missing_sources` = `[]`; `stale_reason` = null; `fallback_active` = false; `envoy_degraded` = false. | **PASS** |
| Read-gating not falsely triggering | All four sources fresh + none in `stale_sources` → the gate returns real values, no spurious LKG/envelope fallback on healthy telemetry (the `last_reported` semantics working — no false-stale). | **PASS** |
| No new URA errors post-restart | `error_log` ERROR scan: the only URA error is the 7-count "Error adding entity None" from the **10:18 pre-v5.92.3 window**; **zero** new URA errors across the v5.93.0 + v5.93.1 restarts (window to 12:15). | **PASS** |
| Clean boot / coordinators healthy | `house_state` = `home_day` fresh; coordinator entities live. | **PASS** |
| Drain-pause HOLD / solar LKG | Internal read-gating, mutation-verified in-suite (RED-on-neuter); engages only on a real freeze → **live = organic** (recorder watch when a genuine stale window occurs). | **Code+test PASS; live = organic** |

**Boot transient noted + dismissed:** `envoy_status` base state progressed `offline` (12:13) → `stale` (12:18) as the *pre-existing* connection-level tracker + hourly-anomaly check warmed up post-restart (`data_anomaly_age_seconds` ~29s, `last_reading_age` ~29s). This is NOT the v5.93.1 per-source union — `stale_reason=null` and `stale_sources=[]` confirm the new logic correctly abstains; the base state is the known Envoy warmup pattern and settles on its own. The per-source freshness attributes prove the Envoy is actually reporting.

Cycle closed. The frozen-read class is now gated (solar/SOC→LKG), the drain pause is held across a stale CT, and per-source staleness is observable on `envoy_status`. Breaker/grid-cap under stale + drain-arm under stale are the two carded follow-ups (`BREAKER-GRIDCAP-STALE-TELEMETRY-1`, `ENVOY-DRAIN-ARM-STALE-CT-1`).
