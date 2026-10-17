# EC storm/blind Stage A: Tier-3 Review A (local correctness)

Branch `feature/ec-stage-a`, base `f2ec3cb38` (three-dot, verified). Spec: `PLANNING_ec_storm_and_blind_decisions.md` Rev 3.3, D-A1 to D-A5.
Targeted tests: 4 Stage A files, 245 passed (the full suite was not run; the orchestrator owns that run).

**Verdict: SHIP.** 0 CRITICAL, 0 HIGH, 0 MEDIUM, 4 LOW.

## Per-site checks (hold)

| Site | Check | Result |
|---|---|---|
| `_reserve_action` energy_battery.py:6449-6532 | fold, then clamp 0-100, then stamp, then stand-down, then deadband | PASS. Stamp happens before the stand-down/deadband return. `reserve_level=None` returns (None, None) with no stamp, which matches the old `if reserve_level is not None` guard. With no floor, the stamp is `int(max(0,min(100,x)))`, identical to the removed `_result` stamp. |
| `_result` energy_battery.py:6593 | sole call, old stamp block removed (:6703) | PASS. The lint tuple was updated at energy_const.py:2329. |
| `_tick_reserve_floor` reset :5522 | entry-reset before the grid-disconnect early return | PASS. Disconnect (:5844) returns before the sighted registration (:5866), so the floor stays None there. |
| `_registered_floor` :6402 | partial/full returns `int(reserve_floor)`, else None | PASS. A sighted full hold registers `int(soc)`, which can be below reserve_soc (P3-08). The fold only raises, so this is harmless. |
| Off-peak re-key :6297, :6340 | `hold_depth=="partial_hold"` changed to `_tick_reserve_floor is not None` | PASS. Every full_hold branch returns (:5868-5935), so only partial_hold reaches these lines, and for partial_hold the floor equals effective_reserve. |
| Blind hold :5683 | `max(F, base)`, never lowers; `compare_to=_desired` only when the write leg is None | PASS. If both are None, one write goes out and the next tick deadbands against the new stamp. |
| Blind de-escalation :5674 | `reserve_soc` folded by the partial floor; full_hold exempt | PASS. INV-1 repro: 20 becomes 50. |
| Blind release :5689 | restores `_blind_pre_raise`; arms only when `folded > base` | PASS. Flags clear on release and on every non-gate tick (:5785). |
| TOU rank energy_tou.py:481-521 | distinct-rate set; ties share a rank; single-rate season gives no top and all-bottom | PASS. DST adds no new code because it delegates to `get_current_period`. |
| `_is_top_rate_edge` :6414 | falls back to the literal when the engine is absent or raises | PASS. |
| Slider read :2652 / fusion :562 / `_full_hold_floor` :741 | junk → default, then clamp 0-100; `max(reserve_soc, partial, slider)` | PASS. Inversion case 20/80/60 gives 80. |
| Number setter number.py:1856 | `int()` + clamp, writes options only | PASS. |

## Findings

- **LOW-1 (Bug Class: latent false trigger, dormant knob):** energy_battery.py:5655-5661. Q6 detection `_wl < _desired and _last_reserve_level != _wl` fires when the cloud write leg lags. Blind hold writes 60. The dispatch tap stamps the ledger to 60. The next tick still reads wl=30, so 30 < 60 and 60 != 30, and the override latches for the whole episode with no manual lower. This only matters if `BLIND_RESPECT_MANUAL_LOWER` flips to True (it is ruled False at rung 1). Fix before anyone flips it: require that the desire was dispatched more than one tick ago, or that the leg once read ≥ desired this episode.
- **LOW-2 (scope drift, ambiguity #6):** inclement.py:758. `_full_hold_floor(None)` also changes the **sighted** path, which is reached when `envoy_avail=True` and `battery_soc is None` on every tier. That path previously held at 100 (BACKUP, energy_battery.py:5935) and now holds at max(reserve_soc, partial, slider), 60 by default. Judgement: **not a principle-1 regression.** Principle 1 forbids forecast/locality from demoting a hold's *depth*. Here hold_depth stays full_hold and only the numeric blind floor follows the Q2 ruling, with slider=100 restoring legacy. In BACKUP mode the reserve number may matter little on the hardware, but I have not verified Enphase behavior and would be guessing. Plan §257 only says "sighted keeps int(soc)", so the plan should record this case explicitly. Doc fix only.
- **LOW-3 (unguarded primitive):** energy_tou.py:513-521. `rate_rank`/`is_bottom_rate` have no guard against an unknown period or a non-numeric rate (KeyError/ValueError), unlike `is_top_period`. Stage A has no caller. Stage B D-B4 will consume it in a trust path, so add the guard (or a try at the call site) then.
- **LOW-4 (seed/read asymmetry):** number.py:837 seeds from `{**entry.data, **entry.options}`, while the reader (energy_battery.py:2652) reads options only. If the key ever lands in `entry.data`, the display and the behavior disagree. It is unreachable today (no config-flow field). The pattern was copied from PeakBufferTarget.

## Notes (cleared)
- When de-escalation runs with base None, it arms release with `pre_raise=None`, and the release then rewrites `reserve_soc`. That is a redundant single write and harmless.
- When blind hold's base is a stale sighted desire (for example arbitrage 80), it writes 80 and never arms release. This matches the spec ("base = last stamped desire"), and the error is on the safe side.
- The sighted fold can now raise an emission under partial_hold that was previously below the floor. This is intended (INV-1). The golden test covers the no-floor case byte-identically.
