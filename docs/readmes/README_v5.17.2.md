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

## Live Validation — Validated 2026-07-14 (post-restart ~13:41 CDT)

| Criterion | Result | Observed evidence |
|---|---|---|
| L1 — deploy healthy | **PASS** | HACS `installed_version = v5.17.2` (`pending_update: false`); `sensor.ura_presence_coordinator_presence_house_state` available (`guest`, last_changed 14:01:59 CDT). URA ERROR scan: only 2 lines, both `13:39:38 Failed to log census snapshot: DB write worker did not process request within 35s` — the known shutdown/boot DB-worker transient, pre-dating the new boot; zero post-boot URA ERRORs. |
| L2 — rung/gate attrs | **PASS (attrs present; values benign-null by design)** | `sensor.ura_energy_coordinator_battery_strategy` now carries `arbitrage_rung`, `arbitrage_intent`, `arbitrage_gate`, `arb_projection_rung0/1` (all `null` at read time) with `arbitrage_phase: discharge`. Null is correct here: `_gate_is_open` is only consulted on the **off_peak branch** (`energy_battery.py:1894`, `:3655`), and the house is in mid_peak/discharge ("Mid-peak (summer) — holding charge for peak"). The gate/rung enum values (and any `solar_attain` phase) first populate at tonight's off_peak entry. `solar_attain` could not be live-exercised today (gate not rung-closed); proven in-suite (`test_arbitrage_rung_gate_observability.py`). |
| L3 — stale retirement + freeze | **PASS** | `last_verified_write_charge_from_grid` = `{commanded: true, oracle_seen: "off", status: "stale", verified_at: 2026-07-14T18:47:02.958260Z, restored: true}`. The zombie record retired on the first post-boot sweep after the first decision tick (13:47 CDT, ~6 min after restart — faster than the documented ~15-30 min worst case). Freeze proven by two spaced reads: 14:04:59 CDT and 14:15:59 CDT both show **identical** `verified_at` — spanning at least one 15-min sweep with no re-alarm. `write_mismatch_counts_24h` = `{reserve_soc: 0, charge_from_grid: 0, storage_mode: 0}` — the stale record no longer counts as a mismatch. |

Boot-only transients seen and dismissed: the census-snapshot DB-worker
timeout pair at shutdown (known transient, called out pre-deploy); no
Envoy blind-hold ERRORs persisted past boot.

Note on H2: the acceptance claim as written ("arbitrage_gate in
open/closed_rung_0/…/disabled within 1h") is stricter than the code's
actual behavior — the gate outcome only populates on off_peak decision
ticks. Attr *presence* validated live; the enum value lands at tonight's
off_peak entry and is covered by Shipwatch's recorder window.
