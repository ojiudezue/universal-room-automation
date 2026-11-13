# Review D — adversarial completeness: HVAC-PRECOOL-STANDDOWN-WHEN-COOL-1

Branch `feature/precool-standdown` @ `584fb91a`, diff base `7c545c0b...584fb91a`. Plan rev 4 §2 invariants.
Read first: `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (complete), §10 ledger respected.

**Verdict: SHIP.** No CRITICAL or HIGH. One MEDIUM (pre-existing, sibling of D1b), recommended in-cycle.

## Surface re-enumerated (greps, not the plan's list)

`_release_banked_zones(` callers, all in `hvac_predict.py`:
| Line | Path | Pre-arrival token possible? | Verdict |
|---|---|---|---|
| :545 | master-OFF `_pa_rel` | yes, by design (`trigger=pre_arrival_inactive`) | owned end path |
| :573 | master-OFF rest (D1b) | no (split out at :540-554) | holds; see D-L1 |
| :643 | restart orphans | **no**: `_banking_excursion_tokens` is RAM-only (empty at boot); boot audit (`hvac.py:1631`) closes S12/S13 BANKING rows `stale_boot_release` before the first cycle (`hvac.py:1700`); a still-live row → foreign skip (`:1155-1165`) | holds; see D-M1 for the non-pre-arrival leak |
| :666 | energy gate-OFF (D1c) | split out at :658-660 | holds for live borrows; see D-M1 |
| :1323 | `async_end_pre_arrival_borrows` | yes, by design | owned end path |

Row closers other than the end path: arrester `human_interrupt` (allowed), `profile_switched` (`hvac.py:7379`, pre-existing, both sites; next pass clears `interrupted`), `stale_boot_release` (allowed), `lease_expiry` (unreachable: window ≤ 110 min < 2 h cap, ended in the first full pass), energy pre-heat D4b (`hvac_predict.py:2128-2142`, foreign skip), energy pre-cool D4b (`:1483-1493`, `caller_site` mismatch → foreign skip).

`caller_site` / `PRE_ARRIVAL_CALLER_SITES` readers: `hvac_predict.py:542, :659, :1304`; `hvac.py:7464`; `hvac_override.py:3968` (C4, feeds INFO-1 `arrival` flag at :3986 → :6089-6123). No raw `== "S12_pre_arrival"` left. Display only: `sensor.py:19204`.

Adds to `_pre_arrival_zones`: only `hvac.py:7257` (spent-episode gated). Adds to `_last_precool_zones`: only `hvac_predict.py:722` (energy loop, added on EVERY outcome incl. `foreign_borrow` and `setpoint_skip`).

Pre-arrival thermostat writes: cool `:1541` (only caller `:784`), heat `:1807` (only caller `:796`).

## Findings

**D-M1 MEDIUM (pre-existing, Bug Class #53 — D1b predicate not applied at the sibling sites).** `hvac_predict.py:647-667` (energy gate-OFF) and `:623-643` (restart orphans) release zones that have NO live borrow. `_release_banked_zones` with no token takes `pre_preset=None` → `is_human_manual_snapshot` True → raw baseline `set_setpoints` (`:1170-1186`), whose only gate is `comfort_delay_active`, which returns False under TAO (`hvac_override.py:2911`). `_last_precool_zones` gains a zone on every energy-loop outcome (`:713-722`), and the ZI prune (`:742-759`) keeps any zone whose live high is below baseline − 0.5.
Repro (legal): summer, EC Energy Saver Pre-Cool ON, scope whole_house, house home_day, home 70/76. A person under Temp Arrester Override sets zone_3 to 68/72. 10:30 energy trigger → `_execute_zone_pre_cool` computes `effective_high = max(73, max(72, 70)) = 73 >= 72` → `setpoint_skip`, but zone_3 is added to `_last_precool_zones`. The prune keeps it (72 < 75.5). 12:00 the operator turns Energy Saver Pre-Cool OFF → `_rel_c = {zone_3}` → raw 70/76 written over the TAO-protected manual. The same predicate gap reaches the restart orphan path (gate OFF at boot + a protected manual below baseline). INV-NO-RELEASE-WRITE names only switch 28, so it is not falsified as written, but the class is the one D1b fixed. Fix: apply D1b's "no token and no live row → skip" at :658 and :627. ~6 lines.

**D-L1 LOW.** `hvac_predict.py:560-568` (D1b) keeps a zone whose `_preheat_excursion_tokens` entry exists. That dict keeps RETURNED tokens until the boundary timer pops them (`:2219`). With a live PREHEAT row the kept zone is skipped as foreign anyway (`:1155-1165`), so the clause only has an effect when the row is already gone, and that effect is a raw baseline write to a zone with no borrow. Narrow reach: the zone must be in `_last_pre_conditioning_zones` (begin cycle only, `:496`, `:2190`) and its latch must already be discharged. Fix: test `not tok.returned`, or drop the `_pht_m` clause.

**D-L2 LOW (hollow guard).** The heat leg "fails closed on unreadable mode" (`:1676`), but `update_zone_climate_state` returns early on `unavailable` (`hvac_zones.py:702-703`), so `zone.hvac_mode` / `current_temperature` keep the last readable values. The `"unavailable"` member of `PRE_ARRIVAL_UNREADABLE_MODES` cannot be reached through ZoneState.
Repro: Carrier cloud outage, zone_2 last read `heat_cool` with T 64; a winter pre-arrival fires → the heat leg begins a borrow and writes to an unavailable entity. The cool leg has the same shape (pre-existing, plan L4 accepts stale T). Fix: read live state, as `_climate_unreadable` (`hvac.py` ~3552) does.

**D-L3 LOW (doc).** The heat baseline keys on `HOUSE_STATE_PRESET_MAP` (`hvac_const.py:1359`; `sleep → sleep`, `waking → home`). The Q7 interrupt reference uses sleep in `waking`. The state-of-play header says "arrival Home heat". In `sleep` the leg targets Sleep heat + 2, and in `waking` the leg and the interrupt reference disagree. Doc wording; behaviour defensible.

## Invariant checklist
| Invariant | Result | Evidence |
|---|---|---|
| INV-SD-COOL | PASS | single caller `:784`; T guard `:1424-1435` precedes `begin_excursion` `:1449`; T None → fail-open write by design |
| INV-SD-HEAT | PASS (caveat D-L2: stale T/mode in an outage) | `:1675-1728` before begin `:1733`; NaN → None (`:82`) |
| INV-ONE-LEG | PASS | `is_borrow_active` re-read `:794`. Cool outcomes deferred/failed/begin-raised → heat evaluated, but heat needs T < low ≤ high < T (inverted → skip `:1702`); T None → heat `no_temp`. Same-row reuse is blocked by the `caller_site` check (`:1486`, `:1766`) |
| INV-LIFECYCLE | PASS | closer enumeration above; no `banking_release` path reaches a live S12/S13 token |
| INV-NO-RELEASE-WRITE (switch 28) | PASS (D-L1 narrow) | `:555-573` |
| sibling: energy gate-OFF / orphan release on borrow-less zone | LEAK (pre-existing) | D-M1 |
| INV-NOOP | PASS by reading | every new branch keyed on `reason == "pre_arrival"` or inside the new function; energy callers ignore the return value |

## Stats
| Sev | Found | Fixed |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 1 (pre-existing) | pending |
| LOW | 3 | pending |

Bug classes: #53 one-missed-site (D-M1, D-L1); hollow guard / #63-adjacent (D-L2); doc drift (D-L3).

## Fix-up disposition (2026-11-12)

D-M1 FIXED at both sites via `_zone_has_borrow_to_release` (energy gate-OFF: `test_energy_gate_off_skips_zone_without_borrow` drives the TAO 68/72 repro; restart orphans: `test_restart_orphan_skips_zone_without_borrow` + `test_restart_orphan_still_releases_live_borrow`; each mutation RED). `test_v5_7_1_energy_precool` C2/C3 updated: C2's banked zone now holds its token; C3's orphan holds a live row. Effect: the orphan reconciliation releases only zones with a still-live row after the boot audit. D-L1 FIXED (unreturned pre-heat token only; `test_master_off_skips_returned_preheat_token`). D-L2 FIXED for the heat leg (live entity read; `test_unreadable_mode_cool_open_heat_closed` drives stale ZoneState heat_cool/T 65 with the entity unavailable/unknown). The cool leg still reads ZoneState (plan L4, fail open). D-L3 FIXED in STATE_OF_PLAY wording.
