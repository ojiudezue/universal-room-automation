# Review D (adversarial completeness, diff-blind): EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1

Branch `feature/ev-rung1-redirect-cap` @ `03eb3b70`, diff base `4df802ab` (parent; plan-approval board commit).
Plan: `docs/planning/PLANNING_ev_rung1_redirect_cap.md` rev2. Not HVAC/presence; state-of-play docs not required.
No pytest run (framing C owns the serial suite); all findings are from source reads with file:line.

## Invariants (falsifiable form) and attempts to break them

| Inv | Statement | Attempt | Result |
|---|---|---|---|
| INV-1 | `_arb_rung1_latch` newly set only if net_power fresh (or max_age<=0) and `ev_load_kw > effective_import_kw`; snapshot == capped credit | Re-enumerated all writers of the latch: `energy_battery.py:937` (init), `:4504` (sole True writer), clears `:4341/4352/4398/4420/4561`. No writer outside the module (repo-wide grep). Credit `:4241-4250` is `clamp(ev-imp,0,ev)`; `:4464` short-circuits credit 0 to rung_2; `:4509` snapshots the same `ev_load_pct_per_h`. Projection is monotone in `extra_rate`, so D1 can only remove entries vs develop | PASS (see D-LOW-1, cross-sensor skew) |
| INV-2 | While latched, `projected_rung0 < exit_band` escalation never fires while `hist[0].t < latched_at`; night/solar-collapse/counterfactual/forecast-closed exits ungated | `:4414-4419` gates only the escalation; night `:4337-4341` runs before the latched branch; solar collapse `:4351`, counterfactual `:4395`, forecast-closed `:4560` untouched. Early returns `:4191/4202/4211/4218` return rung_2 without touching the latch (develop behaviour) | PASS |
| INV-3 | Hold bounded: after K=3 (`:266`) valid post-entry samples, `hist[0] >= latched_at` | Sampler `:5055-5072` appends only non-None SOC, trims to K+1=4. Prod path: entry N double-sampled (`:4189` + `:6049`), N+1 hist=[c,N,N,N+1] held, N+2 hist=[N,N+1,N+1,N+2] flushed. If attain branch returns early (reboot recovery `:6040-6045`) the tick single-samples: hold extends to at most N+3. `bool(_hist)` is always True when reached (rate needs >=2 samples, `:4217`). Window clear (`:5837`, `energy.py:12125`) → `rate None` → rung_2 at `:4218`; reseeded samples are all post-entry → flushed | PASS |
| INV-4 | grid_charge_intent or phase CHARGE → `breaker`, dispatched before battery actions | `energy.py:8186-8209`: `grid_charge_intent` checked first, independent of `_arbitrage_intent`; ordering block unchanged. Only EV-switching consumer of the intent (grep: `energy.py:8179` sole reader; `energy_pool.py:3107` is a log string) | PASS |
| INV-5 | Night: rung/intent/gate/actions identical to develop | Night: `rate_hours=0` → entry projection == `projected_rung0` (already < entry_band) on develop; under D1 credit 0 short-circuits to the same rung_2 earlier. Latch cleared at `:4341` before the D2 hold is reachable. Only display differs (`arb_projection_rung1` None, new attr) — within stated scope | PASS |
| Restart | latch and latched_at both non-restored, consistent | grep: no RestoreEntity / persistence of either; init `:937/:942` | PASS |

Additional surfaces swept: Envoy unavailable (`_read_fresh_power_w` `:2506-2533` → None → credit 0); battery_power stale (`battery_power_w` `:2446-2470` is freshness-gated → None → imp = net, conservative); exporting (negative imp, `min` caps at ev); two EVs (summed `ev_load_w`, single credit); SOC >= target (`:4202` rung_2, unchanged); target <= drain floor (classifier never reads the floor); peak/mid-peak mid-latch (`determine_mode` entry-reset `:6465` clears intent → release; carried latch with old `latched_at` evaluates as flushed = develop); CHARGE window during hold (plan case 21, one-tick delay, accepted).

## Findings

**D-LOW-1 (bounded model error; not an INV-1 violation) — cross-sensor timing skew can over-credit at EV start.**
`energy_battery.py:4242-4249`. The freshness gate allows a net_power reading up to 180 s old, and the EVSE power (`_tick_ev_load_w`, `:6492`) comes from a different poller. Repro: cloudy morning, solar 5 kW, house 2 kW. Envoy net last reported at 10:00:00 as −3 kW (export). The EV starts at 10:00:20 and the EVSE reports 10 kW, or the status-charging estimate does. The tick runs at 10:00:40, before the Envoy's next report. Credit = min(10, 10+3) = 10 kW, while the true redirectable draw is 3 kW. The result is at most one false entry, and only at EV start. On the next entry evaluation (after the flushed escalation at N+2), net is fresh, the credit is correct, and there is no re-latch. Worst case is one off→on cycle per session start, which is the same shape as the stated residual. No fix required. If the trip-wire shows it, the remedy would be to require `last_reported(net) >= EVSE power last_changed`.

**D-LOW-2 (pre-existing, display) — held/latched rung_1 reason text claims `projected X% >= target` when X is the counterfactual below entry_band.**
`energy_battery.py:7303-7308` prints `_arb_last_projection_rung1` (the counterfactual, set at `:4394`). On any latched rung_1 tick it is < entry_band by construction. This predates the cycle. D2 adds no new ticks of this kind except the held tick. The ground truth is unaffected. Card-worthy display fix only.

**D-INFO-1 (pre-existing, not a leak) — latch survives early-return rung_2 ticks (`:4191/4202/4211/4218`).** A later latched tick evaluates with an old `latched_at` and is treated as flushed, which is develop behaviour. No new path.

No CRITICAL/HIGH/MEDIUM leak found. EV emission sites changed: zero (confirmed: `energy.py:8179-8209` and `energy_pool.py` untouched by the diff).

## Verdict

**SHIP.** INV-1..5 and the restart invariant hold across the whole surface. The two LOWs are optional and not must-fix.
