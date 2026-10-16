# Review D: adversarial completeness, EV-FILL-PRIORITY-SOC-CHATTER-1

Branch `feature/ev-fill-priority-buffer` @ b1d5b878d. Base 67e5c66e2 (verified as the merge-base). Tier 3, framing D (diff-blind).

## Invariant (falsifiable)
Under any legal config and any reachable sequence of pause owners and SOC values:
1. FP never leaves a device paused at SOC >= threshold, except for the plan's section 3 exemptions.
2. After a SOC-reached resume with no discharge since, FP makes no membership transition in [thr-band, thr), and pauses as develop does below the floor.
3. An unlatched charger behaves byte-identically to develop.
4. The latch is discharged by the inert window (day boundary), observation mode, force charge, a peer steal, release_all, and pruning.

## Surface re-enumerated (whole file, not only the diff)
Writers of `_paused_by_fill_priority`:
- `energy_pool.py:2914`: EV pause, gated by the latch.
- `:3228`: arbitrage hand-off, gated by a per-id latch term.
- `:3600`: EV release_all re-add when SOC is untrusted. The latch is cleared at `:3568` first.
- `:4135`: plug release_all re-add. The latch is cleared at `:4107` first.
- `:4618`: plug pause, gated by the latch.
- `energy.py` `_restore_registry_owner_lists`: boot only. The latch is RAM-only and empty at that point.

Latch writers and dischargers:
- Producer at `:2981` / `:4676`. It runs only on the terminal SOC-reached resume, after the peer-held, untrusted and grid-charge `continue`s.
- Discharges: inert `:2788` / `:4535`, D5 floor `:2804` / `:4549`, D2 peer steal `:2823` (EV list = every EV_REGISTRY pause owner incl. dp and proactive; plug list = every PLUG_REGISTRY owner), D3 force `:2841` / plug, D4 release_all `:3568` / `:4107`, D6 observation `energy.py:6972`, prune `:1255` / `:4182`.

Derived property: latch ∩ FP-set = ∅ always holds. The producer discards membership, and every add is either latch-gated or follows a clear. Because of this, a latched id can never take the resume, manual-override or hand-off paths, and **(1) cannot be violated through the latch**.

Day boundary: every TOU season must declare off_peak (`energy_tou.py:320`). `peak_ahead_before_offpeak` (`:574-618`) returns True only when a peak hour comes before the next off_peak, and that peak hour is itself inert. As a result, every non-inert stretch (off_peak in daylight, or mid_peak before a peak) is bounded by an inert tick, including in custom schedules. FP always runs either the tick or release_all (`energy.py:6776/6842`, `6942/6968`), both directly under the observation-mode `if` (`:6582`/`:6972`), and there is no early `return` in between.

## Repro probes (quality/tests/review_d_ev_fill_priority_buffer.py, 8 tests, all PASS against production)
| Probe | Result |
|---|---|
| Envoy jump 79→80→81→76 | pauses at 76 (D5 then gate). PASS |
| 81→77.5 holds, 76.9 pauses | PASS |
| Two chargers: latch is per-id; arbitrage steal of B drops only B | PASS |
| Latch ∩ FP set empty across a 12-step SOC walk on 2 chargers | PASS |
| SOC None tick keeps the latch (not a declared discharge) | as designed |
| Plug: band hold, peak inert discharges, then first pause at 79 | PASS |
| Threshold raised 80→90 while latched: pauses at 85 (D5) | PASS |
| Threshold lowered 80→70 while latched: no pause at 68, pause at 66.9 | see L1 |

## Findings
- **LOW L1 (Bug Class #63-adjacent).** `energy_pool.py:2800-2805`: the latch carries no record of the threshold it was set under. If the operator lowers `number.*fill_priority_soc` from 80 to 70 while latched, the floor drops to 67, so a SOC of 68-69 does not get the first pause of the new threshold until SOC < 67 or the next inert window. Legal config (live Number). Impact is one skipped pause, inside a 3-point band, within the same fill window. Optional fix: clear the latch when `soc_threshold` changes (store the threshold as the dict value instead of monotonic time).
- **LOW L2 (dead defensive term).** `:3227`: the hand-off latch term is effectively unreachable. An id reaches the hand-off only from `_paused_by_arbitrage`, and D2 has already popped the latch on the FP tick that followed the arbitrage pause. The producer cannot latch an arbitrage-held id either, because the peer-held path `continue`s first. The term is harmless and keeps INV-4. No action needed.
- **INFO.** A restart mid-band loses the RAM latch, so one legacy pause at 78-79 follows. This is declared in plan INV-1 ("or restart"), so it is not a leak.

No HIGH/MED. The INV-4 unlatched path changed only latch-dict operations: the D5 and D2 loops iterate the latch, the pause gate takes the `else` branch, and the hand-off term evaluates True for unlatched ids.

## Checklist
| Invariant | Verdict |
|---|---|
| (1) no FP pause at SOC >= thr outside exemptions | PASS |
| (2) band no-transition / floor pause | PASS |
| (3) unlatched byte-identical | PASS |
| (4) latch discharge: day boundary / obs mode / force / steal / release_all / removal | PASS (plus L1 threshold-change gap) |

**Verdict: SHIP.** L1 is optional and can be fixed in-cycle.

## Re-verify after fix-ups (HEAD ccb1c9559)

**What changed:**
- c22579c70 removed `_proactive_offpeak_holds` from both peer-steal lists, and the latch now stores the threshold it was set under (D-L1).
- ccb1c9559 removed the plug band kwarg.

I re-ran the enumeration on HEAD and got 16 latch writer/discharge sites. The only new sites are the threshold-change `elif` branches in the EV and plug sweeps.

**Correction to my first pass.** I treated `_proactive_offpeak_holds` as a legitimate steal. That was wrong. It is URA's own ensure-on claim, re-made on every off_peak tick. Counting it as a steal wiped the latch every off-peak-daylight tick, so the band did nothing in that window. A-HIGH-1 is correct.

**Can the latch now survive where it shouldn't?**
- **Off-peak daylight to peak:** peak is inert, so the latch is cleared at the boundary. Probe: PASS.
- **Charger held only by the off-peak hold while SOC drops below the floor:** D5 pops the latch whatever the ownership. Because the charger is OFF, FP makes no claim, which matches develop. Probe: PASS.
- **Ensure-on claim plus a real steal (battery drain):** D2 still drops the latch. Probe: PASS.
- **Night:** off_peak at night is still inert, so the latch cannot reach the next fill window.
- **Invariant (1):** the latch and the fill-priority set still never overlap. While latched, the ensure-on hold can only keep the charger ON or OFF under its own claim, never under fill-priority's.

**Does the threshold-change clear add a new path?**
- **Lowered 80→70:** the first pause now fires at 68, so L1 is closed. Probe: PASS.
- **SOC None with a changed threshold:** the latch is cleared. That is conservative and leaves legacy behaviour. Probe: PASS.
- **Same threshold passed as int or float:** 80 == 80.0, so the latch is kept. Probe: PASS.
- **Plug mirror:** the off-peak hold keeps the latch, and a threshold change clears it. Probe: PASS.
- The clear can only discharge the latch, never set it. In the worst case it returns legacy behaviour, so it cannot violate INV-1..4.

I added 7 probes. The superseded L1 characterization is disabled. Result: 86 passed in total, counting the cycle tests on HEAD plus the review probes.

**Re-verify verdict: SHIP.** No new findings. L1 is fixed, and L2 (the dead hand-off term) is unchanged and harmless.
