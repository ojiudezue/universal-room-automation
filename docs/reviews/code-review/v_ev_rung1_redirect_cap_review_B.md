# Review B — EV rung-1 redirect cap (integration / state-machine integrity)

Branch `feature/ev-rung1-redirect-cap` @ fa49efce (code 03eb3b70), base 4df802ab (three-dot). Plan rev2.
Card EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1, Tier 3. Not HVAC/presence; those state-of-play docs not required.
Tests: `test_ev_rung1_redirect_cap.py` + `test_ec_daylight_horizon_poor_night_floor.py` → 404 passed.

## Findings

| # | Sev | Site | Finding |
|---|---|---|---|
| B1 | LOW | `energy_battery.py:4414-4419`, `:5062` | SOC-None ticks append no sample, so the D2 hold persists across Envoy SOC blips (the window cannot flush). Bounded: night release `:4337`, solar collapse `:4351`, counterfactual exit `:4395` and forecast-closed `:4560` stay ungated, and the plan's INV-3 already scopes the bound to "ticks carrying a valid SOC". No action; noted for the README. |
| B2 | LOW (doc) | `energy_battery.py:4416-4417` | The flushed window still starts at sample N (SOC at the entry tick, taken before the pause is commanded), so N→N+1 includes EVSE actuation latency. Rate is a delta from N, which is the correct origin; not a defect. |

No CRITICAL/HIGH/MEDIUM.

## Integration checks

| Check | Result | Evidence |
|---|---|---|
| Legitimate rung-1 not suppressed (solar-fed EV) | PASS | Credit `clamp(ev−imp,0,ev)` `:4241-4250`; latch path unchanged `:4503-4513`; test `..._value_on_entry_tick` (ev 7, net 5 → 2.0 kW, rung_1) and the 5-tick solar-fed no-flap test (`test_ev_rung1_redirect_cap.py:~690-715`). |
| Breaker ordering / grid-charge pauses EVs before CFG | PASS | `energy.py` untouched by diff; intent mapping `:4572-4583` unchanged; case 21 asserts `pause_reason == "breaker"` on held tick and on CHARGE tick (`test...:735-742`). |
| fill_priority, drain-precedence Path A, overnight onset/ensure-on | PASS | No diff in `energy.py` / `energy_pool.py`; EV emission sites changed: zero. |
| WAIT/CHARGE/HOLD transitions | PASS (bounded delay) | Held rung_1 keeps gate closed one tick → CHARGE delayed exactly one tick; asserted against legacy discriminator (`test...:744-751`). HOLD short-circuit (`:7226`) precedes the gate and is unaffected. |
| EV toggle trip-wire | PASS | Unchanged (`energy.py` not in diff). |
| No-op paths byte-identical (night, no EV, not poor day, peak) | PASS | Night: latch cleared at `:4337-4341` before the D2 block, credit irrelevant (rate_hours 0). No EV: `ev_load_kw > 0` short-circuits the net read `:4242`. Not-poor: gate returns before classifier `:4556-4564`. Peak: classifier not called; only change is D3 display reset `:6466`. Only display deltas (`arb_projection_rung1` None on cap-zero, new attr) as the plan's INV-5 states. |
| Restart | PASS | Latch and `_arb_rung1_latched_at` both init False/None (`:937`, `:942`), neither restored; `None` path → `window_flushed=True` (`:4416`) = develop behavior. |
| Reload | PASS | Fresh `BatteryStrategy` → same as restart. |
| Stale `_latched_at` from a prior episode | PASS | Sole writer `:4505` is the sole latch-True writer `:4504`; read only under latch=True. |
| Multiple ticks per period / per-tick cache | PASS | Cache keyed on `now` `:4177-4180`; second `_gate_is_open` call (`:4606`) is a pure read, so the D2 read and D1 net read happen once per tick. Both callers (`:4606`, `:7247`) and the attain sampler (`:6049`) use the same `now`. |
| History clear while latched (`:5837`, `energy.py:12125`) | PASS | <2 samples → rate None → rung_2 at `:4218` before D2; post-clear samples are ≥ latched_at so flush is immediate after. |
| Duplicate sampler `:4189`/`:6049` | PASS (as planned) | Hold = 1 tick on production path (window trace: N+1 `[N-1,N,N,N+1]` held, N+2 `[N,N+1,N+1,N+2]` flushed); comment corrected; fix carded EC-ATTAIN-RATE-DUP-SAMPLE-1. |
| `_read_fresh_power_w` side effects | PASS | Pure read `:2506-2534`; `max_age<=0` disables freshness (documented kill switch). |
| Untracked tasks / listeners | N/A | No async, timers or listeners added. |

## Verdict

**SHIP.** No must-fix items.
