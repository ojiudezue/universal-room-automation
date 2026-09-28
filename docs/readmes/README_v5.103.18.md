# v5.103.18 — URA takes its thermostats back out of "manual" (the old lockout rule is gone), person protection survives restarts, and the arrester stops overriding live borrows

**Card:** `HVAC-W1-THERMOSTAT-DEFINITION` (W1-B, Tier 3). Plan: `docs/planning/PLANNING_hvac_w1b_thermostat_definition.md` (REV 7, decisions 1–52). Built by `ura-super-builder` (Fable 5.1).

## The problem
A v3.8.0 rule in S1 (`should_change_preset`) refused to write a preset over a zone reading `manual`: "Don't fight manual — that's the arrester's job." Carrier turns every raw setpoint write (nudge, compromise, pre-cool, pre-heat return) into a `manual` hold, and the arrester ignores manuals at ~zero delta, so URA-caused manuals had no owner: 88–661 min strands on zone_1 and 22/22 nudge-echo lockouts. The rule was also, undocumented, the only thing stopping S1 from writing over live borrows. State of play §9e and §10 C25.

## What changed
1. **S1 reclaims `manual`** to its target preset on the next tick unless one of four gates holds for that zone:
   - (a/b) person-protected hold: Temp Arrester Override (TAO) or any immune-person hold;
   - (c) arrester grace, comfort delay or compromise in flight;
   - (d) arrester disabled (passive mode);
   - (e) a live borrow: its self-expiring registry row, or the nudge restore timer / nudge in-flight / compromise timer.

   A deferral writes `preset_change_deferred` with the gate reason. A reclaim's `preset_change` row carries `details.manual_class` ∈ {`zero_delta_ura`, `sub_delta_human`, `gated_human`, `unknown`} and a `gate_snapshot`. An NM trip-wire fires if S1 reclaims the same zone repeatedly in a short window.
2. **Borrow returns are presets-only** (S6/S8/S9/S11/S13). A raw setpoint is written only when the pre-borrow state was itself a human manual (`human_manual_` reason prefix). The write funnels, including resume-then-pin, are unchanged.
3. **Person protection is durable.** Immune holds and TAO are saved in the HVAC zone-state store (side-keys `__immune_holds`, `__tao_state`), saved before shutdown. After a restart or reload, TAO comes back ON only if its 6 h window has not expired. The restart notification says restored / expired / released truthfully.
4. **Arrester booking is one row per detection** with `delta_f` and `gated_reason`: `nudge_win` while a nudge is actually running; an immune person wins over a compromise; passive mode no longer double-books.
5. **The arrester no longer writes over a live borrow** when its grace or compromise timer fires. It used to be able to turn the AC back on during an egress window pause. It now stands down with one `arrester_deferred_to_borrow` row. The startup audit also skips zones with a live borrow.
6. **Retired** the v5.88.0 back-out option "Restore thermostats after temporary changes". Every borrow is now always recorded.
7. **Compromise duration** is clamped to 5–15 min (UI max 120 → 15; stored values clamped).
8. **Restart and lifecycle fixes:**
   - `force_ac_reset` returns the nudge it cancels.
   - An egress pause survives a restart without orphaning its record.
   - A restart mid-nudge no longer resumes a ghost nudge (the boot audit already restored it).
   - A DB error while starting a nudge can no longer leave it stuck in flight.

## Operator rulings (verbatim in the plan ledger)
- **D13:** Nudges win over a human change during the nudge.
- **D48:** Borrow **starts** proceed even when a zone is person-protected. *"URA has more information and should win. URA understands energy saving strategies and Operators don't. They can redo if they want to pre-empt automation changes that are valid."*
- **D49:** The vacancy-away shortcut keeps today's behaviour. It waits for person protection and live borrows (a compromise counts as a borrow), but not for arrester grace or a disabled arrester.
- **D18:** Small human changes (< 1 °F, < 2 °F coasting) that the arrester ignores are reclaimed next tick, logged, with no alert.
- **D17 / D46:** Immune holds persist; TAO restores if still inside its window.
- **D52** (by analogy with D48): hard reset stays gated only on person protection.

## Expected effect
- No more post-borrow `manual` strands or `preset_change_locked_out` episodes; URA reclaims within one 5-min tick when no gate holds.
- ~160 extra Carrier writes/day from post-nudge reclaims (resume + pin), covered by the 120 s preset-kind suppression so they are not booked as overrides.

## Not in this release
- S10 Custom Preset Ranges vs S1 (dormant; card `HVAC-S10-DPM-VS-S1-1`, blocks D9).
- Which Carrier feed confirms a write (`HVAC-WRITE-CONFIRMATION-ORACLE-1`).
- Deferred to after live validation: delete the excursion HIGH-1 manual-skip + parked D3; close `HVAC-PRESET-LOCKOUT-ESCAPE-1` and `HVAC-ZONE1-MANUAL-OSCILLATION-1`.

## Live acceptance (written back after restart)
| # | Criterion | Tells apart |
|---|---|---|
| 1 | All 3 HVAC zones load; zero URA ERRORs at boot | load failure |
| 2 | 0 `preset_change_locked_out` rows after restart; `preset_change_deferred` rows only with a gate reason | old guard still live vs new rule |
| 3 | A zone reading `manual` after a nudge return gets a `preset_change` with `manual_class` within ≤ 1 tick | reclaim works vs strand persists |
| 4 | No S1 `preset_change` on a zone inside an `ac_ramp_events` nudge window | gate (e) protects the borrow vs S1 stomps it |
| 5 | A `tao_restore_evaluated` ledger row at boot | persistence wired |
| 6 | Reclaim trip-wire NM count = 0 in the first day | no Carrier re-manual loop |
| 7 | HVAC options no longer show "Restore thermostats after temporary changes" | retirement landed |

## Review ledger
- **Plan:** 2 Tier-3 plan reviews (completeness + build-prediction) → REV 6 → focused re-review → REV 7.
- **Build:** `e77dd686` / `2297eb8b` / `b444046d` (tag `pre-review-v5.103.18`).
- **Code reviews:** A (local correctness), B (integration/lifecycle), C (test authority via per-site mutation) and D (adversarial completeness) — all FIX-REQUIRED.
- **Fix-up 1** `e199ed0e` / `5648f886` → re-reviews FIX-REQUIRED.
- **Fix-up 2** `28cdab14` → final completeness pass FIX-REQUIRED (restart mid-nudge ghost).
- **Fix-up 3** `e42ecae2`. Merged `11f5bee91`.
- **Orchestrator mutation checks:**
  - gate-(e) row read neutered → 9 RED;
  - S1 verdict ignored → 23 RED;
  - ghost-nudge re-arm restored → RED.
- **Gates:**
  - Isolated name-diff (162 files) → 0 NEW.
  - Full name-diff → 2 NEW = `test_energy_restart_resilience::TestBillingRestoreDaily`, which fails identically on pristine develop after ~19:00 CDT (orchestrator-verified; card `TEST-BILLING-RESTORE-WALLCLOCK-FLAKE-1`).
  - Full name-diff → 38 GONE = the pre-existing order-dependent `test_carrier_freshness` / `test_v47x_weather_manager` family.

## Rollback
Revert the merge. Older code ignores the store side-keys. A stored value for the retired option is harmless.

## Live validation — 2026-09-28 (HACS v5.103.18, HA restarted 20:54 CDT 09-27; v5.103.19 restart 22:15 CDT; window to 08:30 CDT 09-28)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | All 3 zones load; zero URA ERRORs | **PASS** | system_log after both restarts: only boot-transient WARNINGs; zone 3 decided on the first cycle |
| 2 | 0 `preset_change_locked_out`; deferrals only with a gate reason | **PASS** | 0 `preset_change_locked_out`; 2 `preset_change_deferred` rows |
| 3 | URA-caused manual after a nudge reclaimed within one tick | **PASS (stronger than expected)** | 14 nudges; presets-only returns left NO URA-caused manual to reclaim — `manual_class` on 26 `preset_change` rows: 24 `not_manual`, 2 `gated_human` (reclaims after genuine human changes), 0 `zero_delta_ura` |
| 4 | No S1 `preset_change` inside a nudge window | **PASS** | 0 S1 writes inside the 14 `nudge_started`→`nudge_restored` windows |
| 5 | `tao_restore_evaluated` at boot | **PASS** | 20:54:34 `decision=no_persisted_state` (TAO off) |
| 6 | Reclaim trip-wire NM count = 0 | **PASS** | no reclaim-rate NM in `notification_log`; only 2 ordinary "HVAC Override" NMs for the genuine human changes |
| 7 | "Restore thermostats after temporary changes" gone | **PASS** | 0 references in installed `strings.json` / `config_flow.py` |

Echo re-check (v5.103.17): 0 `override_detected` within 15 s of any of the 14 nudges.
