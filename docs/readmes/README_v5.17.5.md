# URA v5.17.5 — Blind-Hold Total Contract

**Released:** 2026-07-15 · **Tier:** 3-grade (framings A/B/C + D completeness) · **Commits:** 5dd4c578 + 0bf0b84d + 51fb1884 + 7af863d4 (build/fix series) + 4c8eaa48 (review record)
**Review record:** `docs/reviews/code-review/v5_17_5_blind_hold_tier3.md` (2 CRIT + 3 HIGH found/fixed)

## The two 2026-07-15 incidents

**Incident 1 — 16:00: blind-hold froze an active grid import into peak.**
The Envoy went telemetry-blind at 14:26. The D1b attain machinery had
legitimately set reserve=80 + charge_from_grid=ON at 15:06 (mid_peak catch-up
covering peak). At 16:00 the old blind-hold guard
(`if not self.envoy_available:`) froze that ACTIVE grid import straight into
the peak period — importing grid at the most expensive rate with no exit. The
freeze was unnecessary on two counts: (a) SOC was being served the whole time
via the 3-tier resolver's cloud fallback (`soc_source: cloud_fallback`); (b)
control writes go to the CLOUD leg under v5.16.1 H1 — a blind Envoy cannot
block them. Had the decision cycle been allowed to proceed on fallback SOC,
the peak branch would have discharged and emitted CFG=off on that very tick.

**Incident 2 — 18:31: the reversion sweep fought the operator.**
With desire-stamps frozen stale by the same blind-hold, the operator manually
de-escalated the battery (reserve 80 → manual). The reversion sweep then
"self-healed" the operator's change back to reserve 80 from its stale desire
ledger — repeatedly — until the operator disabled the energy coordinator
entirely to win. Blind must mean **no decisions AND no re-assertions**.

## Invariants (falsifiable, per Tier-3 protocol)

- **I-BH1** — While telemetry-blind, URA must never CONTINUE an active grid
  import into a higher-rate period; blind-hold may engage only when NO
  resolver tier has fresh SOC.
- **I-BH2** — No FRESH grid-charge entry while on degraded telemetry; the
  import breaker fails CLOSED when import is unreadable.
- **I-D3** — The reversion sweep never re-dispatches from a stale desire:
  desire-freshness gate + post-boot stand-down (post-boot desire is unstamped
  until a sighted decision cycle runs).

## Fix series

| Commit | Content |
|---|---|
| 5dd4c578 | Gate relax: blind-hold triggers only when envoy blind AND `battery_soc is None` on ALL tiers; reason lines gain `(degraded telemetry: <soc_source>)` suffix; blind peak de-escalation safety net (blind + peak/into-peak + CFG last-known ON → emit reserve-down + CFG=off) |
| 0bf0b84d | B-CRIT-1/2: degraded-telemetry FRESH-entry guard (attain + off_peak arbitrage cannot START a grid import on fallback-only SOC); breaker fail-closed on unreadable import |
| 51fb1884 | D3 sweep desire-freshness gate (no self-heal while blind) + A1 cloud-SOC staleness gate (stale cloud → None → blind-hold) + A2 full_hold freshness + C-MED-1 ledger-leg test |
| 7af863d4 | D-HIGH-1: degraded/breaker guards hoisted ABOVE the import-guard grace tick; D-MED-1: no ON-heal of a physically-off import while degraded; D-HIGH-2 disabled stub |

**D-HIGH-2 — DECISION PENDING (operator).** Inclement `full_hold` precharge
can in principle START while degraded. A guard is committed as a **disabled
stub** (1-line wire-up) pending the operator's exempt-bounded vs strict call;
with the stub disabled, behavior is exactly the v5.5.0 status quo, and D's
repro shape is already blocked by the A2 freshness gate. Recommendation on
record: exempt-bounded (A2-fresh full_hold + fallback SOC present required).

## Review summary

Tier-3-grade: framings A (data/staleness), B (entry/breaker correctness), C
(mutation authority), D (adversarial completeness). Findings: **B-CRIT-1,
B-CRIT-2, D3-live, D-HIGH-1, D-HIGH-2 (stubbed), D-MED-1, A1, A2, C-MED-1** —
all fixed except the pending-decision stub. Proofs: 15 executed mutations RED
(builder) + orchestrator independently re-executed the D3 gate mutation
(RED×2, byte-identical restore); framing-D's 3 leak repros re-run against
HEAD: 3/3 pass. Battery suite 166/166, write-verify 83/83.

## Deploy-day operating context

The energy coordinator is **DISABLED** at deploy time
(`switch.ura_energy_coordinator_enabled = off` — operator protection after
the 18:31 sweep fight). Battery is on manual settings: cloud reserve 10,
charge_from_grid off. Re-enable is part of the sanctioned live-validation
plan (L4 below), not an automatic post-restart step.

## Tests

Full suite baseline unchanged: **36 failed / 14 errors** (pre-existing
env-drift failures only; the `test_deploy_scripts` SIGINT-trap failure is
environmental — deploy.sh trap code untouched since v4.7.10).

## Shipwatch acceptance hypotheses

```yaml
project: ura
version: v5.17.5
hypotheses:
  - id: H1
    claim: installed_version == v5.17.5
    oracle: ha_state
  - id: H2
    claim: zero URA ERROR lines
    window: 24h
  - id: H3
    claim: during any envoy-unavailable window with cloud SOC present, battery_strategy reason carries "degraded telemetry" and the coordinator continues deciding (no blind-hold freeze)
    oracle: recorder
    window: 3d
  - id: H4
    claim: no reserve/charge_from_grid write within 10 min of boot that contradicts the pre-boot manual state, UNLESS a sighted decision cycle ran first (post-boot sweep stand-down)
    oracle: recorder
    window: 3d
```

## Live Validation (prospective — write back post-restart)

- **L1:** HACS `installed_version = v5.17.5`; zero URA ERROR post-restart.
- **L2:** energy coordinator still DISABLED post-restart (switch restored off).
- **L3:** with coordinator disabled, NO reserve/CFG writes for 10 min; manual
  10/off state untouched (recorder check).
- **L4:** re-enable coordinator (operator-sanctioned), wait 2-3 decision
  cycles: (a) intent re-derived from scratch (reason populated; no blind
  freeze if Envoy back, or degraded-suffix on fallback); (b) sweep does NOT
  re-dispatch stale 80/ON — post-boot desire unstamped → stands down; any
  write within 10 min must come from a fresh decision (evening off_peak →
  drain-target park ~30, NOT 80); (c) write-verify records transition sanely.
