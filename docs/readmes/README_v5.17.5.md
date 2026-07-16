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

## Live Validation — Validated 2026-07-15

Deployed + HACS v5.17.5 installed; HA restarted 19:24–19:26 CDT. Cloud legs
watched: `number.iq_battery_hacs_battery_reserve` +
`switch.iq_battery_hacs_charge_battery_from_grid`.

| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Version + zero URA ERROR | **PASS** | HACS `installed_version = v5.17.5`; only URA-module ERROR post-restart = 2× "Failed to log census snapshot: DB write worker did not process request within 35s" at 19:25:22 — during the restart shutdown flush (DB worker stopping), not steady state |
| L2 | Coordinator still DISABLED post-restart | **PASS** | `switch.ura_energy_coordinator_enabled = off`, restored 19:26:17 |
| L3 | No URA reserve/CFG writes for 10 min while disabled | **PASS (with cloud-truth finding)** | Zero service calls in the window. Reserve entity DID flip 10→80.0 at 19:32:21, but with **no service-call context** — it was the Enphase integration's first post-boot cloud poll reading back cloud truth. The operator's 18:36 manual "10" had never landed at Enphase cloud (18:21 WriteVerifier: `reserve_soc REVERTED (commanded=80, oracle=10.0)`); the 80 is residue of the pre-fix 18:31 sweep fight, cloud-side. CFG restored `off` at 19:28:08 (poll) |
| L4a | Re-enable → intent re-derived from scratch | **PASS** | Coordinator ON 19:38:49 (operator-sanctioned). First sighted cycle 19:40:52: mode `self_consumption`, reason "Peak — battery covers load, solar exports **(degraded telemetry: cloud_fallback)**", SOC 66.6 via cloud fallback, `envoy_available: false` — decided on degraded telemetry, no blind freeze (I-BH1 relax path live) |
| L4b | Sweep does NOT re-dispatch stale 80/ON | **PASS** | No 80/ON write anywhere post-boot. Reserve went 80→**10.0 at 19:40:33** — again no service-call context: oracle/poll readback coincident with URA's first sighted cycle (CFG verify tick 00:40:33.939Z), i.e. cloud settled to the operator's delayed 10, URA read it, wrote nothing. `last_verified_write_reserve_soc` still the restored pre-boot record (`restored: true`); `write_mismatch_counts_24h` all 0. CFG stayed `off` the entire window. Post-boot desire stand-down held (I-D3) |
| L4c | Write-verify transitions sanely | **PASS** | Restored ledger records verified against live oracle without dispatching: CFG record `commanded: true / oracle_seen: off / status: stale / restored: true` (00:40:33Z) — correctly classified stale rather than re-asserted (the exact 18:31 failure shape, now standing down) |
| Bonus | A1 cloud-SOC staleness gate live | **OBSERVED** | By 19:52 the cloud SOC aged out → `soc_source: fallback_stale_reject`, `soc: null`, reason "Envoy unavailable — holding (no commands issued)" — blind-hold engaged ONLY once no tier had fresh SOC, with reserve 10 / CFG off (nothing active frozen). Both halves of I-BH1 exercised live within 15 min |

No drain-target write was expected or seen in the window: TOU period was
**peak** (next boundary `mid_peak_starts` +60 min), so the sighted decision was
peak discharge at floor 10 — consistent, not the stale 80.

Boot transients seen and dismissed: pre-existing `homeassistant.core` "Unable
to remove unknown job listener" lines at 19:38:49 fired by the entry reload on
re-enable (also present at 18:34 pre-deploy under v5.17.4 — not new to this
build; listener-cleanup noise, tracked separately).

**Operator note:** the Enphase cloud reserve carried 80 (not the manual 10)
from 18:31 until ~19:40 — the manual de-escalation had silently not stuck
cloud-side. It now reads 10 with CFG off; battery matches the intended manual
state, and URA's fresh decisions agree with it.
