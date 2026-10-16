# EV-FILL-PRIORITY-SOC-CHATTER-1: Tier 3 Review B (integration / state-machine / restart)

Branch `feature/ev-fill-priority-buffer` @ `b1d5b878d`. Merge-base verified as `67e5c66e2` (three-dot diff).
HVAC/presence state-of-play docs do not apply (energy only). Targeted tests: `test_ev_fill_priority_repause_band.py` + `test_energy_pause_release_hygiene.py` give 91 passed.

## Verdict: FIX-REQUIRED (A-HIGH-1 confirmed; no new HIGH)

The one must-fix is Review A's A-HIGH-1. I confirmed it independently and found no other recurring self-claim among the D2 peers.

## D2 peer audit: genuine steal, or a recurring self-claim that wipes the latch?

A latch is set only on a terminal resume. The peer-held branch at `energy_pool.py:2937-2953` (`continue`) runs before the producer at `:2981`. So when the latch is set, no grid_cap, drain, us, arbitrage, load_shed or blind_window owner holds the id.

| Peer (EV) | Add sites | Steal or self-claim | Evidence |
|---|---|---|---|
| `_proactive_offpeak_holds` | `:1763` | **SELF-CLAIM. Wipes the latch on every off_peak tick.** | Off-peak ensure-on step 2d claims every ON charger it doesn't hold on each off_peak tick. FP is active in off_peak daylight (`:2766`). **Confirms A-HIGH-1. Remove it from D2 (`:2830`).** |
| `_paused_by_grid_cap` | `:2246`; `:3644` is keep-claim only | steal | Added only with a `turn_off` on a charging EVSE above the cap. |
| `_paused_by_battery_drain` | `:2500` | steal | Idempotent, but only while charging, discharging and `soc_low` (drain floor, far below the FP band). A real pause. |
| `_paused_by_us` (TOU) | `:1397`, `energy.py:1603` (KV restore), `:3545` keep-claim | steal | Peak/mid_peak only, and only with a `turn_off` while ON. Off_peak discards it. In mid_peak with TOU on, the charger is TOU-held, so FP's resume takes the peer branch and no latch is set. |
| `_paused_by_arbitrage` | `:1690` (breaker clamp), `:3111/:3119` | steal | The proactive claim of an OFF charger runs only while `arbitrage_charging` is true (breaker or rung-1 redirect). That is a real other owner. On release, the hand-off at `:3221` re-adopts into FP. The latch is already gone, so FP takes the charger with one transition, owned by arbitrage. Acceptable. |
| `_paused_by_load_shed` | `energy.py:8776/8789`, KV restore `:2823` | steal | Shed event only. |
| `_paused_by_blind_window` | `:1472`, `:2074` | steal (LOW note) | `will_pause` includes `not is_on`, so an OFF charger is claimed every tick while the guard is engaged. The guard engages only when SOC is unresolved and the reserve is unverifiable. In that state the band has no value, and the next first pause is the legacy edge. |
| `_paused_by_dp` | `energy.py:5590` | steal | Added only on a dp transition. Note: dp is **not** in the terminal-resume peer list (`:2937`), so a latch can be set while dp holds the id. D2 pops it on the next tick. Harmless. |

| Peer (plug) | Steal or self-claim |
|---|---|
| `_proactive_offpeak_holds` (`:4024`) | **SELF-CLAIM. Same as EV. Remove it from `:4562`.** |
| `_paused_by_us` (`:3950`) | steal (peak/mid_peak, ON only) |
| `_paused_by_battery_drain` (`:4327`) | steal |
| `_paused_by_load_shed` (`energy.py:8891/8905`) | steal |

## Findings

### B-HIGH-1 = A-HIGH-1 (confirmed, not new): `_proactive_offpeak_holds` as a D2 peer
- **Where:** `energy_pool.py:2830` (EV) and `:4562` (plug).
- **Bug class:** #63. "A peer holds it" is being used to mean "a new session started".
- **Repro:** see A-HIGH-1. Off_peak with `is_daylight=True`. FP resumes at 80 and sets the latch, then ensure-on adds the id at `:1763`. On the next tick D2 pops the latch, and SOC 79 re-pauses.
- **Fix:** remove it from both lists. Update the A8 parametrization. Add a sequence test: off_peak-daylight resume → `determine_actions("off_peak")` → SOC 79 gives no `turn_off`. No other peer needs removing (table above).

### B-LOW-1: replug inside the band does not reset the latch
- **Where:** there is no unplug/replug discharge. The latch is keyed by evse_id at `:2982`.
- **Scenario:** latched at 80. The car leaves, and a different car plugs in while SOC is 78. FP does not pause it, so it charges from the home battery until SOC < 77.
- **Bound:** 3 percentage points of battery. The same daily D1 inert discharge applies. This is the band behaving as designed, not a leak. **Document it; no code change.**

### B-LOW-2: one extra pause after restart, reload or observation-exit inside the band
- **Where:** the latch is RAM-only (`:595`). D6 at `energy.py:6978`.
- **Scenario:** latched, SOC 78, then HA restarts or the entry reloads. The latch is empty, so the first tick pauses (legacy edge). The FP set is restored from KV, so there is no lost pause. The worst case is one off/on cycle per restart. This matches plan A14/D6 intent. Accept it.

## Cleared (holds because)

| Check | Evidence |
|---|---|
| The latch affects only the FP gate | There are only two read sites that gate behaviour: the FP pause gate (`:2903` / `:4608`) and the arbitrage→FP hand-off (`:3226`). TOU, drain, dp, grid_cap, load_shed, blind_window, arbitrage pause/breaker clamp and force-charge never read it. A latched charger is still paused by each of them. |
| Arbitrage WAIT/rung-1, breaker clamp | Pause paths (`:3093-3122`, `:1690`) do not read the latch. Hand-off: if the latch is set, the charger is not adopted by FP. The latch can only survive to that point if the arbitrage claim and release both happen before the next FP tick. Even then the charger resumes only in band, which is the band's intent. Breaker-safety is untouched: the breaker clamp runs pre-decision in `energy.py:7374`. |
| Charge-onset deferral | `_charge_on_or_defer` (`:960`) mutates no owner sets. A deferred resume still latches. That is correct: in band, onset turns the charger on later; below the floor, D5 pops the latch, and the legacy rule applies (FP pauses only ON chargers). |
| Excess-solar deferral | Runs before the gate on the global verdict (`:2888`), unchanged. |
| Force charge | D3 unconditional pop (`:2841` / `:4570`). Force charge bypasses FP as before. |
| Envoy SOC untrusted | `battery_soc` is Envoy → LKG (5 min) → cloud, else None. With None, D5 is a no-op and `pause_conditions_global` is False, so this is identical to legacy. The producer is skipped by the untrusted-refusal `continue` at `:2956`. |
| TOU edges | pre-peak mid_peak→peak and off_peak-night are inert, so D1 clears. Post-peak mid_peak is inert, so D1 clears. Sunrise inside off_peak: the latch was already cleared overnight. Off_peak-daylight→pre-peak mid_peak: the latch persists within one fill window (intended). |
| KV restore at boot with SOC in band | The latch is not persisted. `_paused_by_fill_priority` restore is unchanged, so behaviour is legacy (B-LOW-2). |
| Observation mode mid-band | D6 `else` clears both latches on every observation tick, with no dispatch. On exit the latch is empty, so the first pause is the legacy edge. |
| Toggle OFF | D4 clears in `release_all_fill_priority`. The plug clear runs before the grid-charge early return (`:4107`). |
| Device removal | Prune (`:1257` / `:4183`). |
| Byte-identical: unlatched | Every new statement is either `id in latch` or iterates the latch, which is empty for an unlatched id. D6 clear is a no-op on an empty dict. |
| Byte-identical: band 0 | Floor = threshold. D5 pops every latch whenever SOC < threshold, before the gate. A surviving latch therefore implies SOC ≥ threshold, so the pause verdict is False and `_fill_priority_would_hold` is False. The gate and hand-off outputs equal develop. |
| Tick ordering | FP (`energy.py:6817`) runs after TOU/ensure-on and drain, and before arbitrage (`:7375/:7476`). D2 sees peers claimed on earlier ticks. Nothing awaits between the D5 sweep and the gate inside the pool method (synchronous). |

## Stats

| Sev | Found | New in B |
|---|---|---|
| HIGH | 1 | 0 (A-HIGH-1 confirmed) |
| LOW | 2 | 2 (document only) |

Bug class frequency: #63 ×1, design-note ×2.

**Must-fix:** A-HIGH-1. Remove `_proactive_offpeak_holds` from the EV (`:2830`) and plug (`:4562`) D2 peer lists, and add an off_peak-daylight ensure-on sequence test. No other D2 peer change is warranted.
