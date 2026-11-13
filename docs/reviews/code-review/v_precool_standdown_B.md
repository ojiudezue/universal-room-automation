# Review B — async / lifecycle / restart / cross-coordinator — HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1

Branch `feature/precool-standdown` @ `584fb91a`. Diff base: merge-base `9701c938` (verified, three-dot).
Plan `PLANNING_hvac_precool_standdown_and_seasons.md` rev 4. Framing B only; review A (`v_precool_standdown_A.md`)
not duplicated (A-M1 false stand-down row stands; nothing here changes it).

Read first, completely: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (743 lines, §9e, §10 C1-C39).
No §10 claim is re-asserted. No code/doc contradiction found on the surfaces below.

**Verdict: SHIP (framing B).** No CRITICAL/HIGH/MEDIUM. Two LOWs, both inherited shapes; fix-optional.

## Lifecycle trace of the new heat leg (`hvac_predict.py:1650-1838`)

| Phase | Path | Holds because |
|---|---|---|
| Begin | `begin_excursion(kind=BANKING, site=S13_pre_arrival)` `:1734` | Row enters `_rows` synchronously before the DB await (`hvac_excursion.py:922`), so any concurrent begin (arrester compromise, nudge, energy pre-heat) sees it. A refused begin goes through D4b (`:1756-1773`) — only an own `S13_pre_arrival` row may be written over. |
| Write | `set_setpoints(... site S13_pre_heat, reason pre_arrival)` inside `auto_release_on_incomplete` `:1778` | Deferred/raised write → CM releases the row; token stored only after `mark_committed`. |
| Interrupt during begin/write | `_bt.returned or _interrupt_latched` `:1782` → spend episode, return `interrupted` | Same M1 shape as cool. A person's change during the write await returns the token in `_rows`; the stored returned token is popped with no write by the D2b guard (`:1080`) and cleared `interrupted` + spent by `hvac.py:7461-7474` (now `in PRE_ARRIVAL_CALLER_SITES`). |
| Arrival / timeout / inactive / max age | `async_end_pre_arrival_borrows` `:1304` (filter generalised) via `hvac.py:2438` BEFORE S1 `:2463`; fast run `hvac.py:6016-6026` | Presets-only release of `pre_preset`; max age counted from the borrow's own `started_ts`; zone timeout bounds a late heat begin. |
| Master 28 OFF | `_pa_rel` `:540` → trigger `pre_arrival_inactive` + spend | The heat zone is always in `release_set` (added at `:805` each pass it is not latched). D1b (`:560-571`) drops only zones with no token and no live row. |
| Energy gate OFF | D1c `:656-666` | Leaves S12/S13 pre-arrival tokens to the pre-arrival end path. |
| Restart mid-borrow | boot audit BANKING branch `hvac_excursion.py:1249-1295` | Stale-boot `_auto_return` pins `pre_preset` (HIGH-1 skip for `manual`), row cleared; tokens and `_pre_arrival_zones` are RAM (`hvac.py:809`), so nothing re-hydrates and no orphan token remains. BANKING (not PREHEAT) is the right kind: PREHEAT would rehydrate with no owner. Tested `test_preheat_boot_audit_releases_row`. |
| Lease expiry | `stale_ts` = start + `EXCURSION_LEASE_MAX_S` (duration None) | Never reached in practice: window <= 110 min and max-age end runs every full pass. |
| ZI off / HVAC off | `hvac.py:1922`, `:7539-7545` | Generic over the token dict; spends. |
| Switch 35 OFF mid-window | `hvac.py:7228` | Blocks new triggers only; a live heat borrow ends at arrival/timeout/max age — same as cool, pre-existing semantics. |

## Cross-coordinator

- **S1 on arrival:** end path runs at `hvac.py:2438`, S1 at `:2463`, predictor at `:2501`. On a non-arrival tick gate (e) (live row) keeps S1 off the borrowed zone. Holds.
- **Arrester Q7 / INFO-1:** `hvac_override.py:3967-3968` generalised; a person ending the heat leg takes the arrival reference, and a nudge on top records `arrival=True`. Tested `test_preheat_interrupt_uses_arrival_reference`.
- **Echo:** write recorded in the `emit_set_temperature` ring before the wire; temp suppression 15 s. Same as cool.
- **Energy pre-cool on a heat-borrowed zone:** begin refused, `_is_own` requires `caller_site == "S12_pre_cool"` (`:1486`) → `foreign_borrow`. The zone is still added to `_last_precool_zones` (`:722`, pre-existing R5 shape) but D1c and the prune (`:742-759`, high unchanged by the heat leg) discharge it.
- **Energy pre-heat on a heat-borrowed zone:** refused by its D4b (`:2128-2140`, own requires `S13_pre_heat`). Tested `test_energy_preheat_refused_over_prearrival_heat`.
- **Nudge / AC ramp / S10:** gate (e) is kind-agnostic; the heat leg adds no new nudge interaction beyond the existing BANKING one.
- **Carrier manual hold:** D48 (borrow starts win) applies as for cool; a `manual` snapshot releases via the HUMAN_MANUAL raw-baseline branch (`:1170`). Accepted ruling, not new.

## No-op path

No pre-arrival zone → new code executes only `_standdown_logged &= …` / `_band_inverted_logged &= …` (RAM sets) and the counter rollover on the daily hinge (`hvac.py:2332-2341`). No write, no row, no task. Energy gate-OFF with no pre-arrival token → `_rel_c` equals the old set. Byte-identical. D1b's change is intended (no raw baseline write on a never-borrowed zone).

## Untracked tasks / timers / listeners

None added. The heat leg has no `async_call_later` (no timer return; the end path owns it). Counters are `DailyCounter(persist=False)` (`hvac_predict.py:221-234`) — reset on restart, declared display-only. Membership flags RAM; a restart clears `_pre_arrival_zones` too, so at most one extra truthful row after a restart.

## Findings

| # | Sev | Site | Finding | Bug class |
|---|---|---|---|---|
| B-L1 | LOW | `hvac_predict.py:772-830` | Ordering: the pre-arrival block runs before the once-per-day energy pre-heat (`:808-824`) in the same pass. A live S13_pre_arrival borrow makes `_execute_pre_heat` skip that zone `foreign_borrow`, and `_pre_heat_triggered_today` is already set, so that zone gets no energy pre-heat that day. Reachable only for a pre-arrival heat borrow live inside the pre-heat lead window before off-peak end on a winter day <= forecast low. The zone is being heated toward the arrival target anyway; inherited from the cool leg's BANKING row. Accept or note. | cross-coordinator precedence |
| B-L2 | LOW | `hvac_predict.py:1779` | The heat leg's CM trigger is `s13_preheat_wire_failed`, the energy pre-heat's string (`:2146`). A deferred/failed arrival pre-heat is indistinguishable from an energy pre-heat in `hvac_excursion_events` except by the row's `caller_site`. Rename to e.g. `s13_prearrival_wire_failed` if the probe keys on trigger. | observability |

Cleared (beyond the trace): concurrent begin between the cool return and the heat begin — `is_borrow_active` re-read at `:794` plus begin's REJECT; cool `deferred` and heat `began` cannot both occur in one pass (cool begins only for T > eff_high, heat only for T < eff_low <= eff_high, so comfort-delay churn is not doubled); `_maybe_log_prearrival_standdown` never raises; `_last_prearrival_skips` is entry-reset at `:501` before the master-OFF early return.

## Tests run (targeted)

`test_hvac_prearrival_conditioning.py`, `test_hvac_w1w2_finish_part_a.py`, `test_hvac_w1w2_finish_part_b.py`, `test_hc_precool_oc_observability.py`: **267 passed** (`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`). Lifecycle tests present for boot audit, master OFF, ZI off, max age, interrupt (in and after begin), arrival, foreign borrow, energy pre-heat refusal, deferred write. Tree clean after run.

## Summary

| Sev | Found | Fix required |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 0 | — |
| LOW | 2 | optional (B-L2 is a one-string change) |

Bug-class frequency: cross-coordinator precedence x1, observability x1. QUALITY_CONTEXT candidate: none.

## Fix-up disposition (2026-11-12)

B-L1 ACCEPTED (the zone is being heated toward the arrival target anyway; inherited from the cool leg's BANKING row). B-L2 FIXED (trigger `s13_prearrival_wire_failed`; `test_preheat_wire_failure_trigger_is_prearrival`).
