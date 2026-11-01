# EC reserve false-revert fix-up — Review D (adversarial completeness, diff-blind)

Branch `fix/ec-reserve-false-revert` @ 80b755e45, base 8e2e9b7b7 (three-dot). Tier 3, framing D.
Source verified in worktree `.claude/worktrees/agent-aa982dae5f298d6ae` (read-only).

## Surface re-enumerated
- `write_reverted` / `alert_type="reverted"` emission: ONE site, `energy_write_verify.py` `_sweep_surface` (gate at ~1303, emit/NM ~1330-1350). Confirmed by grep; plan section 4 holds.
- Sweep call site: `energy.py:7410`, runs every decision cycle AFTER the decision/dispatch of the same tick.
- Other reserve alert paths (unchanged, non-goal N1): `_check` MISMATCH (~1032 D3 live-only), `schedule` self-heal starvation (~844 D3 live-only).
- Ledger writers of `_last_reserve_level(_at)`: `energy_battery.py:8197`, `energy.py:2107` (restore), `5682`, `5778`, `10000`. All route anchor moves through `ledger_anchor_moves` / `_anchor_moves`; same value never re-anchors (`energy_battery.py:360`).
- Dispatch while the Envoy sensor is unavailable: `_reserve_reference_decision` rule C (`energy_battery.py:~7547`) sends the PLAIN target (no nudge) whenever cloud differs by >= deadband. So the ledger value stays C during an outage; the memory key (C, first_at >= T_c) survives. X6 nudge flip does not occur on the outage path.

## INV-F1 attacks (no false REVERTED after witnessed landing)
| Attack | Result |
|---|---|
| Rule-C same-value re-sends every tick during outage | holds: anchor does not move, ledger value unchanged |
| Envoy flaps within a sweep | holds: one `trusted_local_reserve` read cached in `_sweep_witness`, gate uses it; no await between step and gate |
| Cloud blip/restart re-reading V | holds: value-based compare |
| Oracle raw None at the confirming sweep, Envoy drops before next sweep | LEAK (fail-closed, LOW): no stamp → page as today. Probe P3: 0 cloud unavailable rows in window |
| Restart during outage | pages (accepted R3, fail-closed) |
| Cloud moves V→V2 (≠C) while Envoy still up, then drop | pages (outside INV-F1 premise; fail-closed) |

## INV-F2 attacks (real reversion still pages)
| Case | Repro | Result |
|---|---|---|
| (a) revert while Envoy up, trusted | C=20, local→10 | step clears memory; gate false → pages. PASS |
| (a') revert to V>C under low-SOC guard (C=20, V=30, soc=21) | reason `low_soc_guard` | memory NOT cleared, but gate requires reason `"unavailable"` → `_local_confirms` False → pages. Later drop: record already REVERTED → coalesced (no un-page). PASS |
| (b) Envoy down, cloud moved to W≠V | | oracle ≠ cloud_at_first → pages same tick. PASS |
| (c) revert to exactly V during outage, Envoy returns with V | | first return sweep: gate needs `"unavailable"`, local V contrary → clear → pages. Decision earlier in that tick may send C but local still reads V in-tick. PASS (late page fires) |
| (c') revert to V during outage, healed before return | C=20, V=10, drop 23:05, app sets 10 at 23:30, cloud reads 10 | next tick rule C sends 20 (cloud 10 vs 20) BEFORE the sweep; if it lands, Envoy returns reading 20 → re-stamp, NEVER pages. See D-LOW-1 |
| (d) never landed | no confirm after T_c | no memory → pages. PASS |
| Different command during outage | ledger D≠C | mem.value ≠ D → pages. PASS |
| Same value re-commanded after a different value (C@T1, D@T2, C@T3 in outage) | | first_at < T3 → pages (fail-closed). PASS |
| Oracle unconfigured / other integration | | sweep returns at oracle check / value compare unaffected. PASS |
| Kill switches | `RESERVE_LOCAL_WITNESS_ENABLED=False` → reason `disabled`, never stamps; memory switch False → step+gate inert | PASS |
| Very long outage (586/714 min) | | no age cap; late page on return as (c). PASS |

## Findings
- **D-LOW-1 (doc overclaim, #63-adjacent)** — plan INV-F2(c) / R2 say detection is "deferred, not lost". False when the strategy's own rule-C send (`energy_battery.py` rule C, runs every tick before the sweep at `energy.py:7410`) re-applies C during the outage: the revert is healed silently and the returning Envoy shows C, so no page ever fires. Not a regression: pre-cycle the nightly drop already left the record REVERTED and the B-MED-2 coalesce (`energy_write_verify.py` `was_reverted` return) would also have swallowed a later real revert in the same outage. Fix: reword R2 to "deferred, or lost if URA's rule-C re-send heals it before the Envoy returns".
- **D-LOW-2 (fail-closed gap)** — oracle raw None at the only confirming sweep before a drop → no memory → false page. Plan probe shows 0 occurrences; accept.
- **Note (non-goal N1, not this cycle)** — rule-C plain same-value re-sends during outage feed `schedule()`; `_check` MISMATCH and self-heal starvation keep live-only D3, so they remain possible false pages at the nightly drop. Plan claims none observed since v5.103.89; not verified here.

## Invariant checklist
- INV-F1: PASS (residuals R3, D-LOW-2 fail closed)
- INV-F2 (a)(b)(d)(e): PASS
- INV-F2 (c): PASS for the stated late-page case; "never lost" wording LEAK (D-LOW-1, doc only, no regression)
- INV-F3: not re-proved here (Review B lane); kill-switch reasoning consistent.

## Verdict: SHIP
Must-fix: none. Should-fix: reword plan R2/INV-F2(c) per D-LOW-1.
