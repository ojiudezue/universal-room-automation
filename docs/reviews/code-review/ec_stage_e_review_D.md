# EC storm Stage E — Review D (adversarial completeness, diff-blind)

Branch `feature/ec-storm-stage-e` @ f2001b333, base `pre-review-ec-stage-e` = fa7e1ffe2 (verified = merge-base).
Plan: `docs/planning/PLANNING_ec_storm_stage_e.md` Rev 3.2. Targets INV-7, INV-8, INV-9.
Repros D-1 and D-2 were run against the real `determine_mode` through `_ec_stage_e_harness` (throwaway probe test, removed; tree clean).

## Findings

### D-HIGH-1: a non-corroborable (unlisted/widened) prepare record moves a table product's event time T, buy schedule and floor. Breaks INV-7(f) and INV-7 falsifier #1. Bug class #53 / #63.
`inclement.py:1260-1268` (`_apply_prepare`): `pstart` = earliest start over **all** `prep`, with no filter on `corroborable`. `key_row` = earliest of `prows`, and `prows` can be an unlisted record. `schedule_buy_hours(..., pstart, ...)` (`:1328`) freezes S against that T, and the INV-8(i) `fstart = pstart - lead` (`:1347`) also uses it.

**Repro (legal; run):** winter 2026-12-16, `inclement_hold_added=["Flood Watch"]`, option on, WSW confirmed (min_temp 20, pop 80), SOC 20, knob 80.
- WSW alone (Onset 21:00): S = {14,15,16}, floor from 14:00, CFG on 14-16.
- WSW + Flood Watch (Onset 11:00): S = {09,10}. CFG turns on at 09:00, and the reason reads "Winter Storm Warning, onset **11:00**". h_req was 3 but only 2 slots fit before the unlisted product's onset. After 11:00 the Flood Watch leaves `prep`, but S stays frozen against the stale T: no buy at 11-16 while the cheap hours before 21:00 are available, and the floor holds at 80 from 09:00 to 21:00.
- Variant (falsifier #1, literal): Flood Watch (unlisted, Onset 11) + Freeze Watch (table, eligible, confirmed, Onset 21). `pclass` = watch and `key_row` = Flood Watch, so the CFG-on reason, latch and schedule are keyed to a product **outside the buy set**. Eligibility comes from the Freeze Watch through `_zone_buy_confirmed(prows)`.
- Cost variant: with an unlisted onset just after a top block (e.g. 10:00 winter, h_req ≥ 2), S takes a rank>0 hour. That is a top-rate WSW buy caused by an unlisted product.

**Fix:** compute `pstart` and `key_row` over corroborable records only. If none is corroborable, keep today's path, which gives the lower floor only. Add a mixed-fixture test: the WSW decision with and without the unlisted Flood Watch must be identical.

### D-MED-1: frozen S keeps a T owned by a different alert after that alert onsets (table-only, pre-existing T definition plus the new freeze). INV-9 spirit.
Same lines. Table-only repro: Freeze Watch (Onset 11:00) + WSW warning (Onset 21:00), SOC 20. `pclass` = warn and key = WSW, but T = 11:00, so S = {09,10}. At 11:00 the Freeze Watch becomes active, yet S is still frozen at T=11, so h_req is under-bought and nothing is re-planned for the 21:00 event. The plan's rule 6 covers only NWS Updates. Fix together with D-HIGH-1: freeze `T` as part of the key, or discharge S when the stored T ≠ the current `pstart`.

### D-MED-2: S can be non-contiguous, which gives a second CFG on→off cycle per frozen schedule (INV-9 falsifier #3, and the E2.3 "Not built: rebuy").
`schedule_buy_hours` (`inclement.py:1104-1116`) takes the h_req best slots with no contiguity. **Repro (run):** winter, WSW Onset 23:00, SOC 20 at 12:00 gives S = {16,21,22}. CFG turns on at 16:00. At 17-20 the TOU branch `_result(charge_from_grid=False)` emits turn_off (`energy_battery.py:~7237`), and CFG turns on again at 21:00 with the latch still `engaged`. That is two on→off cycles per schedule: exactly the second buy and rebuy dependence that E2.3 parked. The floor of 80 does hold through 17-20, so the economics are fine. **Operator decision:** either amend falsifier #3 and E2.3 (accept the split), or constrain S to the contiguous run ending closest to T.

### D-LOW-1: observation mode does register an INV-8(ii) floor within a tick, so the plan's non-guarantee text is wrong (builder's open risk, adjudicated).
The freeze (`inclement.py:1327-1334`) and the `hours[0] <= now` registration (`:1343-1345`) both run inside fusion before `energy.py:9429` clears `_preonset_buy_schedule`. Every observation tick re-freezes and, once now ≥ min(S), registers `preonset_floor = target`. That reaches `_tick_reserve_floor` and the `tick_preonset_floor` column. It is harmless: nothing is dispatched, the value and timing equal what live would do (never before min(S)), and the INV-8 falsifier #1 still holds. **Code wins:** fix the plan's INV-8 non-guarantee to "(ii) is re-derived each observation tick and never persists across ticks". No code change.

### D-LOW-2: restart mid-buy discharges bought energy until T−4.
After a restart at 16:30 (SOC 50, Onset 23:00) the latch and S are empty. The re-freeze gives S = {21,22}, so (ii) does not apply before 21:00 and (i) only from 19:00. 17:00-19:00 discharges in the top block. This is inside the stated non-guarantee, so it is noted only.

## Cleared (holds because)
- **INV-7(a)** holds: `_overlay` never touches `row[3]` (`inclement.py:253-270`); `polygon_topup_records` gates both EXACT and the 60-min cap (`:147-170`); polygon rows are excluded from `prepare` and from `confirmed` (`energy_battery.py:3010`); the unlisted synthetic row has `polygon_local=False`.
- **INV-7(b)** holds: every zone buy (warn `:1422`, watch off-peak `:1510`, D-B6 `eligible`) goes through `_zone_buy_confirmed` (same record: eligible AND confirmed).
- **INV-7(c)** holds: `buy = … & hold & can_buy & corroborable` (`:164-168`). Widened and unlisted records get `precharge_eligible=False`. All three watch corroboration legs AND `corr_ok` (`:1460-1480`), for `watch_requires_corroboration` True and False. The overlay cannot mint a warn, so the warn tier is table-only.
- **INV-7(d)** holds at runtime (`& hold`). **INV-7(e)**: `INCLEMENT_PRODUCT_TABLE` is only read; `_resolve_selection(None)` = the table.
- **INV-8 eligibility-loss discharge** holds: `:1285-1292` pops S and an `engaged` latch on option-off or unconfirm, before use. The forecast latch makes "unconfirm" effectively unreachable until the alert ends.
- **Other CFG-on paths in prepare:** active full-hold legs return before prepare. Arbitrage CHARGE and attain are pre-existing TOU buys that D-B6 yields to (`energy_battery.py:6453-6454`), out of INV-9 scope and unchanged. Redispatch and write-verify only re-send commanded state. No new bypass was found.
- **Engine missing or raising** gives S = (), so there is no D-B6 buy.

## Invariant checklist
| Invariant | Verdict |
|---|---|
| INV-7(a) locality / cap | PASS |
| INV-7(b) zone buy needs same-record forecast | PASS |
| INV-7(c) non-corroborable caps | PASS |
| INV-7(d) buy ⊆ hold | PASS |
| INV-7(e) table default | PASS (not re-run; golden is C's lane) |
| INV-7(f) no change to co-active table product | **LEAK (D-HIGH-1)** |
| INV-8 floor window | PASS, plus D-LOW-1 doc fix |
| INV-9 cheapest/closest, one on→off | **LEAK (D-MED-1, D-MED-2)** |

## Verdict: FIX-REQUIRED
Must fix: D-HIGH-1, and D-MED-1 with it (same site). D-MED-2 needs an operator ruling: accept and amend the spec, or force contiguity. D-LOW-1: plan text fix.

---

## Re-pass @ e4bdcecc9 (fix-up d2687080d..e4bdcecc9)

These findings come from reading the code statically at file:line. No new executed probe was run, because the validator owns the worktree.

### Prior findings: status
- **D-HIGH-1: CLOSED on every path.** `inclement.py:1325` `basis = corroborable or prep`. Class, `prows`, `key_row` and `pstart` (:1326-1334) now come from `basis`. Each downstream path reads `basis` values only:
  - reason/`preonset_event`: `key_row`.
  - latch: `key_id`.
  - schedule: `schedule_buy_hours(..., pstart)` at :1405.
  - INV-8(i) `fstart`: `pstart - lead`.
  - `eligible`/`buy_forecast_confirmed`: `prows`.

  The (i) `hi` test still scans all of `prep`, but it requires `r.corroborable`, so an unlisted record gets only `lower` (INV-7(c) holds). Pinned by `test_unlisted_prepare_never_moves_table_event_time` and `..._never_names_the_buy`.
- **D-MED-1: CLOSED.** The stale-T rule at :1374-1376 deletes `sched[key]` when the stored T ≠ the current `pstart`, and S is re-frozen against the new T on the same tick. Pinned by `test_stale_event_time_replans_after_earlier_alert_onsets`.
- **D-MED-2: CLOSED by operator ruling.** `schedule_buy_hours` (:1141-1155) returns one contiguous run.
- **D-LOW-1/2:** unchanged and accepted.

### New mechanisms
**(a) Contiguous scheduler: holds.**
- An all-cheapest run of length L totals L·min_rate, the global minimum, so a higher-rate run can only win on an exact tie. A tie gives an equal total, which is not a loss.
- The `get_current_rate` → rank fallback cannot mix units in practice. `energy_tou.py:472-478` reads the same `import_rate` that `period_rank` (:491) parses, and `period_rank` returns None when that rate is non-numeric, so the slot becomes unranked and breaks the run.
- An unranked slot breaks a run: the `None` skip.
- UTC stepping makes DST and midnight safe (local rank per slot).
- The horizon filter only trims the head of `seq`, so it never creates an interior gap.
- When fewer slots than `h_req` fit, the run shrinks to the longest available.

**(b) Update carry-over (`_carry_over_updates` :1162-1189).** Wrong-Event (watch→warning) does not carry: it is keyed on Event+NWSCode. When two same-Event records are live at once, the old ID is still in `live`, so nothing carries. Two leaks are LOW:
- **D2-LOW-1 (carry fires on Onset, not only on supersession; bug class: state×time seam).** The latch purge comment (:1313) treats "Onset reached" as a discharge, but carry-over runs first and transfers the latch whenever any departed key has a same-Event/code, window-overlapping successor in prep.
  - Repro (legal): Winter Storm Watch A (table, confirmed), Onset 18:00, Ends 06:00. Same-code Watch B (adjacent segment) Onset 02:00, Ends 12:00. Both are in prep, key = A. A buys to the knob, so `latch[A]=reached`.
  - At 18:00 A onsets, and `latch[B]=reached` is inherited. A's partial hold lets SOC drain toward `partial_floor` from 18:00 to 02:00. B's floor (i) registers at 22:00, but the `reached` latch suppresses B's buy, so B onsets near the partial floor. Without carry-over, B would re-buy to the knob in the cheap hours.
  - This is equivalent to NWS having issued one long alert, so it is defensible. Fix option: carry only when the old ID is not in the current active-hold set (i.e. it was superseded, not onset).
- **D2-LOW-2 (stale-T drops the carry metadata, so a `reached` latch is lost on a later Update and causes a re-buy; bug class #53 one-missed-site).** Carry-over needs `sched[old]` with its meta. The stale-T rule (:1375) deletes the whole entry, and a `reached` state never re-freezes. The same happens after eligibility loss (:1364-1366).
  - Repro (legal): Freeze Watch (Onset 11:00, table) + WSW (Onset 21:00), key = WSW, T = 11. The buy reaches the target at 10:xx. At 11:00 stale-T deletes `sched[WSW]` and `reached` stays.
  - At 15:00 NWS sends a WSW Update with a new ID and the same Onset. With no sched entry there is no carry, so the old latch is purged and the new ID starts fresh. If SOC < target, a second buy runs, which breaks plan §E2.2.6 "a `reached` latch survives: no re-buy".
  - Cost impact is small: it tops up in the cheapest run. Fix option: keep the meta in the latch, or on stale-T replace the hours instead of deleting the entry.

**(c) Degenerate-window fallback (:266-276): narrowing holds.** Only `Ends` null AND `Expires ≤ start` is revived. An explicit `Ends ≤ Onset` stays inverted. `Sent`-as-start can never trip it, because Expires > Sent.
- **D2-LOW-3 (residual).** A revived record also extends `update_alert_memory` retention, from Expires to Onset+`INCLEMENT_ALERT_MAX_HOLD_H`. Rule (3) `left_feed` only fires on a NON-EMPTY healthy feed. So if NWS lets a null-Ends watch lapse at Expires and the feed goes empty, memory keeps it until Onset+MAX_HOLD. Before this fix the record had an inverted window and never acted.
  - This follows the module's fail-toward-hold doctrine and needs a rare lapse with no successor. Noted only.

**(d) Non-key purge and key delete on eligibility loss (:1360-1376): holds.** The purge order is: carry-over, then the live purge, then eligibility loss, then the non-key purge, then stale-T. Every exit leaves at most `sched[key_id]` with T == the current `pstart`.
- An empty S is never frozen (:1410).
- A latch for a non-key ID is not purged until it leaves `live`. This is harmless because the latch is only read for `key_id`.

### Doc
- **D2-LOW-4:** `PLANNING_ec_storm_stage_e.md` contradicts itself. Line 411 says carry-over was built, but :414 ("Accepted, not engineered … carry-over would add the state × time seam") and :656 ("carry-over option is declined") still describe it as declined. Line 128 still carries the `(rank, T−H)` ordering text next to the SUPERSEDED note. Fix the text.

### Re-pass invariant checklist
| Invariant | Verdict |
|---|---|
| INV-7(a)-(e) | PASS (untouched by the fix-up except `basis`) |
| INV-7(f) | PASS (D-HIGH-1 closed) |
| INV-8 | PASS |
| INV-9 contiguity / cheapest / latest | PASS |
| INV-9 no re-buy after reached (§E2.2.6) | LEAK, LOW (D2-LOW-1/2, small cost) |

### Re-pass verdict: SHIP
No CRITICAL, HIGH or MEDIUM findings. D2-LOW-1 and D2-LOW-2 are recommended in-cycle LOW fixes (each a few lines). D2-LOW-4 is a doc fix.
