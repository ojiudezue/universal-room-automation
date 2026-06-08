# PLANNING — Day-Boundary-Blind TOU Decision (summer mid_peak hold fix + shared primitive)

**Tier:** **Tier 2-DB — operator-elevated** (not DB-sensitive, but regression-prone:
battery-strategy decision change with battery ↔ grid ↔ cost ripple, AND it touches a
**shared primitive** — the TOU engine — read by multiple coordinators). Per the standing
policy (CLAUDE.md, operator-coined 2026-06-08: route all regression-prone work through the
3-review protocol). **3 framing-disjoint reviews + live validation + README write-back.**
Proposed framings: **A** = correctness + edge cases (the `peak_ahead_before_offpeak` walk:
hour/season/midnight boundaries, lookahead exhaustion, pre/post-peak windows); **B** =
cross-coordinator + precedence + no-flap (battery hold↔discharge transition can't oscillate
at window edges; arbitrage path + EVSE off-peak ensure-on unaffected; `get_next_transition`
consumers incl. HVAC `max_runtime` unchanged intra-day); **C** = test authority + day/cycle-
boundary (tests drive real schedule from `energy_const.py`/rate table, not hand-copied hours;
season-boundary + midnight cases covered).

**Origin:** Operator observed URA forcing grid import during the summer **post-peak**
mid_peak window (8–9pm CDT) while the battery sat idle at 68% SOC. Root-caused live
2026-06-08 to the summer mid_peak "hold-for-peak" branch, which predates and was never
reconciled with the v4.5.0 grid-arbitrage redesign. Operator framed it as a **bug class**
to sweep, not a one-off.

---

## Institutional context verified

**Greps / reads run (file:line + result):**
- `energy_battery.py:1031-1041` — **BUG site.** Summer `mid_peak` branch sets
  `reserve_level = int(soc)` unconditionally ("Mid-peak (summer) — holding charge for
  peak"). `git blame` → commit `6078155d`, **v3.10.5 (2026-03-11)**.
- `energy_battery.py:1042-1057` — shoulder/winter mid_peak **discharge** branch (the
  correct "no peak this season" behavior). REUSE as the post-peak summer fall-through.
- `energy_battery.py:1010-1025` (peak), `:990-1006` (storm), `:563-578`
  (`_is_charge_window_open`), `:534-561` (`_classify_target_day`), `:650-666`
  (`_gate_is_open`), `:1106-1128` (off-peak drain) — all swept **SAFE** (peak = current-
  period only; arbitrage path already day-aware).
- `energy_tou.py:262-304` `get_next_high_rate_transition` — **REUSE pattern.** v4.5.0 D8
  real-time, midnight-crossing, season-aware forward walk; returns next mid_peak/peak or
  None. Caveat: returns "now" if currently inside a high-rate hour, so it is NOT directly
  usable from a mid_peak tick to answer "is a *peak* ahead before off_peak" → NEW helper.
- `energy_tou.py:199-235` `get_next_transition` — **SUSPECT (in scope).** Intra-day walk;
  the wrap-to-next-day branch (226-233) reads only `self._rates[season]` for *today's*
  season and never advances month → wrong table on a season-boundary day. Load-bearing
  consumer = HVAC `max_runtime` (`energy.py:3105-3110`).
- `energy_const.py:15-34` — summer schedule: `off_peak (0,14)+(21,24)`, `mid_peak
  (14,16)+(20,21)`, `peak (16,20)`. Confirms mid_peak is a **two-window bracketed period**.
- `energy_pool.py:488-561` (EVSE off_peak ensure-on, v4.7.28) — swept **SAFE** (current-
  period only). Confirms the just-shipped cycle does NOT have this class.

**Prior art / sweep:** full energy-domain sweep catalog (this session) → exactly **one**
charging-decision instance of the class (the BUG above); EVSE + arbitrage + pool/plug all
day-boundary-safe. HVAC `max_runtime` (`energy.py:3105`) + mid_peak coast (`energy.py:3077`)
are adjacent SUSPECTs → **deferred to hygiene bucket** per operator (this cycle = charging +
shared primitive, no HVAC behavior change).

**No new CONF_/sensor/entity** introduced — pure decision-logic + a TOU-engine helper.

---

## D1: New day-boundary-aware TOU primitive

Add `TOURateEngine.peak_ahead_before_offpeak(now=None, lookahead_hours=24) -> bool` in
`energy_tou.py`. Walk forward from the top of the next hour using `get_current_period(dt)`
(inherently season/month/midnight-safe): return **True** on the first `peak` hour, **False**
on the first `off_peak` hour, keep walking through `mid_peak`. Returns False if neither found
within `lookahead_hours`. This answers "is a real peak still ahead of me before the next
off_peak" from inside a mid_peak tick — which `get_next_high_rate_transition` cannot (it can
return the in-progress period).

### Acceptance Criteria
- **Test:** at summer 15:00 (pre-peak mid_peak) → True; at 20:30 (post-peak mid_peak) → False;
  at 13:00 (off_peak, peak ahead at 16:00) → True; at 22:00 (off_peak, no peak before next
  off_peak day-rollover until 16:00 tomorrow) → True only if a peak precedes the next
  off_peak boundary (document the chosen semantics). Shoulder/winter (no peak) → False.
- **Test:** crosses midnight and a season boundary without reading the wrong season table.
- **Verify:** pure function of `now` + rate table; no I/O, no side effects.

## D2: Gate the summer mid_peak hold on D1

Rewrite `energy_battery.py:1031-1041` summer branch: hold (`reserve_level = int(soc)`,
"holding charge for upcoming peak") **only if** `self._tou.peak_ahead_before_offpeak(now)`;
otherwise fall through to the existing shoulder/winter **discharge** logic (1042-1057). The
discharge fall-through must reuse the existing code path (no duplicate logic). Pre-peak
behavior is byte-unchanged; only the post-peak window flips hold→discharge.

### Acceptance Criteria
- **Verify:** summer 15:00, SOC>reserve, peak ahead → mode self_consumption, reason
  "holding charge for upcoming peak", reserve_level = SOC (unchanged from today).
- **Verify:** summer 20:30, SOC>reserve, no peak ahead → mode self_consumption, reason
  "Mid-peak (summer, post-peak) — discharging" (or reuse shoulder/winter reason),
  reserve_level = reserve_soc → battery discharges.
- **Test:** both windows covered with a mocked `now` + summer season + the PEC schedule.
- **Live:** during the next summer post-peak mid_peak (20:00–21:00 CDT), battery discharges
  to cover load (`current_battery_discharge` > 0, grid net import drops toward 0); strategy
  sensor `reason` reflects post-peak discharge; reserve_battery_level drops to reserve_soc.
- **Live:** pre-peak mid_peak (14:00–16:00) still holds (regression guard).

## D3: Harden `get_next_transition` season-wrap (shared primitive)

Fix the wrap branch (`energy_tou.py:226-233`): when wrapping to the next day, compute the
period table from `get_season(now + 1 day)` instead of today's `season`, so a season-boundary
day returns the correct next-day transition. No intra-day behavior change.

### Acceptance Criteria
- **Test:** on the last summer day (Sep 30), `get_next_transition` late-evening returns the
  next-day (shoulder) first transition, not summer's.
- **Verify:** intra-day results byte-identical to current behavior (regression guard).
- **Note:** HVAC `max_runtime` consumer is thereby de-risked WITHOUT touching HVAC code.

## D4: Document the bug class

Add **"Day-Boundary-Blind TOU Decision"** to `docs/QUALITY_CONTEXT.md`: a charging/load
decision that acts on an adjacent/upcoming period assumption without a real-time, midnight-
crossing, season-aware lookahead; symptom = fires identically for both halves of a bracketed
period. Correct pattern = consult `get_next_high_rate_transition` / `peak_ahead_before_offpeak`.

---

## Out of scope (tracked)
- HVAC `max_runtime` (`energy.py:3105`) + mid_peak coast (`energy.py:3077`) → hygiene bucket
  ([[project-hygiene-bucket-yaml-span]]).
- No EVSE-gating change (operator confirmed reserve is not an EVSE hold).
