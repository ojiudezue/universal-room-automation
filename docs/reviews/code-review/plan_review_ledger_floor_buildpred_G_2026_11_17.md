# Plan review: interior ledger floor (§1b), build-prediction + G, 2026-11-17

Verdict: **PLAN-FIX-REQUIRED**. The Q4 decision paragraph (§1b, after §1b.10) was appended but never folded into §1b.2-§1b.8, so two readings both compile.

1. **HIGH: Q4 Select is not in the spec it changes.** §1b.7 says "Rung 1 for all ... only by reviewed code"; Q4 adds a rung-3 `select.ura_interior_floor_strategy`. It is missing from the knob table, the deliverables, the tests, entity placement (CM device?) and restore/persistence. INV-IV-FLOOR and the F-D1 mutation ("max instead of min" → RED) assume min only. Builder reading A: a constant min. Reading B: a Select with both. Fix: fold Q4 into §1b.2/.5/.6/.7.
2. **HIGH: `window_max` is under-specified.** Window length (same `SUSTAIN_S`? 60?), coverage rule (None when uncovered?) and None-sample handling are all unstated.
3. **HIGH: "the `interior_floor` rows".** No such row kind exists. Reading A: fields on `interior_lift` rows (lift only). Reading B: a new per-tick row, which is a per-tick DB write (Bug Class: write flood). Pick one.
4. **MEDIUM: strategy switch mid-window.** Does a switch take effect next tick? Is the ring shared? A lift made under max persists after switching to min. Is the lift counter tagged by strategy?
5. **MEDIUM: tick cadence unnamed.** The ring bound "sustain + one tick" and the coverage test depend on it. D0 samples at 30 s, so the sustain 0/30 gates sit below the probe's resolution.
6. **LOW: INV-5 byte-identical vs new `snapshot()` fields.** State whether the fields are present when the knob is off.

**G:** passes. It feeds census and the ledger, not presence (the quote is honoured). It is display-only, with no AWAY reader. A dead or stuck camera adds 0 to a lower bound, so no signal is invented. Members are resolved through the registry. The change is minimal (a defaulted keyword, after the resident lift). One caution: an unproven `window_max` can lift `L` live. That is display-only and the operator asked for it, so it is acceptable.
