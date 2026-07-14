# URA v5.17.2 — Arbitrage Rung Observability + Write-Verify Ledger Retirement

**Type:** Tier 2 feature cycle (two framing-disjoint reviews, both SHIP, LOW-only findings)
**Review record:** `docs/reviews/code-review/v5_17_2_rung_observability_ledger_retirement.md`
**Commits:** 3517edab (rung observability), a0cca9e1 (ledger retirement), b073c2cd (review record; develop tip)

## Part A — Arbitrage rung/gate observability + `solar_attain` phase

**Operator-driven (Bug Class #55, computed-but-not-surfaced):** when the
attainability ladder closed the arbitrage gate (solar alone projected to
attain the target), the strategy sensor showed phase `n/a` — which read
as "arbitrage is broken" when the system was actually making a benign,
correct decision.

New attributes on `sensor.ura_energy_coordinator_battery_strategy`:

- `arbitrage_rung` — which attainability rung the ladder selected
- `arbitrage_intent` — what arbitrage wants to do this tick
- `arbitrage_gate` — gate disposition: `open` / `closed_rung_0` /
  `closed_rung_1` / `closed_forecast` / `disabled`
- `arb_projection_rung0` / `arb_projection_rung1` — the SOC projections
  the ladder ranked

Phase now reads **`solar_attain`** (not `n/a`) when the ladder closed the
gate, with the reason explaining it, e.g.
"rung_0: solar projected to attain X% ≥ target by boundary — no grid
charge needed."

## Part B — Write-verify STATUS_STALE ledger retirement

Previously, a write intent whose strategy desire had since converged with
the oracle (a "zombie" intent) re-alarmed as **"reverted"** on every
15-minute verify sweep, forever — polluting the panel and mismatch
counts with non-actionable noise.

Now such stale intents **retire as status `"stale"` with a frozen
`verified_at`** timestamp. Genuine reversions — where the strategy desire
still wants the commanded value but the oracle disagrees — are
**unchanged**: they still alarm, still count mismatches, still self-heal.

**Documented nuance:** a restored (post-reboot) "reverted" record retires
on the sweep AFTER the first post-boot decision tick (~15-30 min),
because desire is `None` at boot and a `None` desire never retires
(fail-safe: we never retire an intent we can't prove is stale).

## Shipwatch Acceptance Hypotheses

```yaml
version: v5.17.2
hypotheses:
  - id: H1
    claim: installed_version == v5.17.2
    oracle: hacs
  - id: H2
    claim: >
      Within 1h of restart, sensor.ura_energy_coordinator_battery_strategy
      attribute arbitrage_gate is present and one of
      open/closed_rung_0/closed_rung_1/closed_forecast/disabled.
    oracle: ha-recorder
    window: 1h
  - id: H3
    claim: >
      Within 1h of restart, last_verified_write_charge_from_grid.status
      == "stale" (the live 12:17 zombie record finally retiring).
    oracle: ha-recorder
    window: 1h
  - id: H4
    claim: zero URA ERROR logs over 24h (boot transients excluded)
    oracle: ha-logs
```

## Live Validation (prospective — to be replaced post-restart)

- **L1:** HACS `installed_version = v5.17.2`; house_state sensor available; zero URA ERROR post-restart.
- **L2:** `arbitrage_gate` / `arbitrage_rung` attrs present with sane values; if the gate is rung-closed, phase reads `solar_attain` with the explanatory reason.
- **L3:** ~35 min post-restart, `last_verified_write_charge_from_grid` shows status `"stale"` with frozen `verified_at`; re-read 5 min later shows `verified_at` UNCHANGED (proves the freeze). If still `"reverted"` at 40 min, check whether a decision tick has run and report with timestamps.
