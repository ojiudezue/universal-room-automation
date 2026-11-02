# EC savings money — Review B (restart / lifecycle / DB / cross-coordinator)

Branch fix/ec-savings-money 7016bfe4 vs develop ca3a0eb6 (three-dot). Cycle tests: 44 passed.

**Verdict: SHIP** (no CRITICAL/HIGH).

## Findings
1. LOW — energy.py `_ensure_arbitrage_inventory_loaded` (~4343): a transient restore failure or Envoy SOC None at first tick seeds 0 kWh, and the next save overwrites a good persisted row. The SOC cap only lowers kWh, so the inventory under-counts until the next charge. Bug class: stale data source #7. Optional fix: defer the load while SOC is None.
2. LOW — the lifetime total (baseline + ALL rows) double-books energy charged on cutover night. Legacy charge rows already booked it, and the SOC-seeded inventory books it again at discharge. One-time, display only; today/cycle are filtered. Record it in the README.
3. LOW — `cycles_today` / `pace.cycles` now count discharge TICKS, not cycles (semantic change, display). Rename it or document it.
4. LOW — `_apply_arbitrage_tick` (~4444): an exception after `inv.add` and before `drain`/`cap` leaves a partial mutation. The caller's try (~7803) logs it. The cap corrects drift.
5. LOW — sensor.py:12135 docstring ("battery covers nighttime") is stale after D7.

## Cleared
- Persistence: lazy restore on the first applied tick (DB ready), 12h age gate, corrupt input treated as absent. Saves every 3 changed ticks (≤96/day) plus unload in `_async_persist_state` (DBShuttingDown handled). Crash loses ≤15 min.
- Midnight: no inventory reset. DST 11-01: elapsed comes from epoch timestamps.
- Migration: guarded idempotent ALTER. `NOT NULL DEFAULT 'charge'` is legal and makes legacy rows read 'charge'. The kill-switch path still writes 'charge'.
- INV-SHADOW-1 holds. `predicted_import_kwh` has one consumer, the display sensor (sensor.py:12164). `current_effective_rate` in the strategy sensor is a display attribute only. `arbitrage_status` and the `query_arbitrage_*` readers are display/baseline only. No battery/drain/EVSE input changed. The charge path still advances `_arbitrage_prev_soc` before returning.
- Accumulate early returns: net None still yields drain plus unsplit charge. An exception returns None. A rate exception keeps the tracker ts, so the next tick spans the gap (≤1h).
