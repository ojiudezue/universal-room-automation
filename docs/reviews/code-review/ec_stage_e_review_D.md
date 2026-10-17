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
