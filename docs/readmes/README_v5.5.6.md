# URA v5.5.6 — Arbitrage grid-import guard: exposed in config flow, default OFF

Makes the previously-**hidden** arbitrage grid-import guard a config-flow knob, and **defaults it OFF**. The guard used to be an always-on 12 kW abort on the battery's arbitrage grid-charge — invisible (no UI), decoupled from the operator's actual ceiling, and on high-AC summer afternoons it aborted the whole pre-peak pre-charge (AC + a 20 kW battery charge blows past 12 kW), leaving the battery under-filled going into peak. The Enphase battery firmware now curtails its own draw to the breaker, so the software guard is redundant for safety; URA no longer imposes a hidden second limit.

## What ships (Tier 2-DB)
- **Guard is now a config-flow toggle (default OFF) + a required-when-enabled kW field with NO default** ("1+c"): off is a real off; the instant you enable it you must enter *your* DER breaker's continuous rating (amps × 240 × 0.8 ÷ 1000) — no guessed 12 silently re-imposes a limit.
- **Disable mechanism is a single load-bearing assignment:** when off (or enabled with no valid threshold), the effective threshold collapses to `inf`, so all four guard consumption sites (`energy_battery.py` :1120 helper, :1473 arbitrage CHARGE, :2594 attain re-check, :2705 attain entry) no-op uniformly — no per-site guard to keep in sync (Bug Class #53 foreclosed).
- **Hand-edit hardening:** `enabled=True` with `kw` None / ≤0 / non-finite is treated as DISABLED (effective `inf`), never as a finite 0 threshold that would brick arbitrage; a one-time WARNING logs the silent-disable.
- **Sensor honesty:** `sensor.ura_energy_coordinator_battery_strategy` reports `arbitrage_grid_import_guard_enabled` and reports `arbitrage_grid_import_guard_kw` as `null` when off (never a phantom 12).
- Untouched by design: the EV Grid Import Cap and the load-shedding cascade (distinct mechanisms); the guard *code* is kept as a dormant opt-in (not deleted).

## Review — Tier 2-DB (3 framing-disjoint) + orchestrator verification
A (correctness) SHIP, B (state-machine/restart) SHIP, C (test authority) FIX-FIRST → **C-HIGH-1**: sites 3 & 4 mutation tests were tautological (compared in the test body); rewritten to drive real `_run_attain_branch`. **Orchestrator independently re-verified all 4 sites by per-site source mutation** (each test fails when its site is bypassed; caught a macOS `.pyc` staleness false-negative on sites 2 & 4 before confirming). C-MED-1 (kw=0 foot-gun) clamped. Ledger: `docs/reviews/code-review/v5.5.6_arbitrage_guard_expose.md`. Cycle tests 24/24; full suite zero new regressions.

---

## Shipwatch acceptance hypotheses (state oracle: HA recorder + battery_strategy attrs)

**Immediate (post-restart):**
- **H1 — guard inert by default.** On the default install, `sensor.ura_energy_coordinator_battery_strategy` attr `arbitrage_grid_import_guard_enabled == false` and `arbitrage_grid_import_guard_kw == null`. Verdict: violated if enabled true or kw shows a finite number without the operator enabling it. Window: post-restart now.
- **H2 — config-flow surface present.** The Energy Coordinator options screen shows the "Arbitrage Grid-Charge Import Guard" toggle (OFF) + a blank "Grid-Charge Import Guard (kW)" field. Window: post-restart.
- **H3 — no new URA errors** at boot attributable to the guard change. Window: post-restart.

**Delayed (next battery grid-charge — the headline):**
- **H4 — no spurious guard abort with the guard off.** During any arbitrage CHARGE / attain grid-charge window (next poor-tomorrow night), `arbitrage_guard_aborted_at` does NOT advance even if effective grid import exceeds 12 kW (AC + battery charge). Signal: `arbitrage_guard_aborted_at` stays at its pre-deploy value through a grid-charge that pulls >12 kW. Verdict: violated if the guard aborts a chunk while disabled. Window: next grid-charge (may be days out — tomorrow_solar_class must be poor/very_poor to trigger arbitrage grid-charge; not exercised on moderate-tomorrow nights). The ENABLED path (byte-identical to old guard) is proven in-suite, not live.

## Live Validation — PROSPECTIVE (write back after restart + first grid-charge)
| # | Criterion | How |
|---|---|---|
| L1 | Deploy healthy | v5.5.6 HACS-installed, config loaded, zero new URA errors |
| L2 | Guard inert by default (H1) | battery_strategy attrs: `..._enabled: false`, `..._kw: null` |
| L3 | Config surface (H2) | toggle OFF + blank kW field visible in Energy options |
| L4 | No spurious abort (H4) | next grid-charge >12 kW does not advance `arbitrage_guard_aborted_at` |
