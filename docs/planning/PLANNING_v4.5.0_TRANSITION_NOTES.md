# PLANNING v4.5.0 — Transition Notes for Next Session

**Purpose:** Capture the false starts, misconceptions, and corrections from the 2026-05-06 → 2026-05-07 design conversation that produced `PLANNING_v4.5.0_battery_strategy_redesign.md`. Read this BEFORE re-planning anything in v4.5.0. Several of these mistakes are seductive and easy to repeat.

**Authoritative plan:** `PLANNING_v4.5.0_battery_strategy_redesign.md` (this is the good outcome).
**This doc:** the path from bad to good, plus the load-bearing reasons for each correction.

---

## Mistake 1: "Add a v1_legacy / v2_simplified mode toggle for safe rollout"

**What I proposed:** Ship v4.5.0 behind a `battery_strategy_mode` config switch defaulting to `v1_legacy`. Calibrate v2 for 4-8 weeks, then flip default. Migration cycle to ease users in.

**Why it was wrong:** URA has exactly **one production install** — the user's. There are zero other users to preserve compatibility for. Mode toggles, calibration phases, and migration cycles are scaffolding for users who don't exist.

**The correction (user direction):** "Only 1 use Ura for now. So we don't need backward compatibility."

**The right approach:** Just ship the new behavior. No mode toggle. No legacy path. Live validation IS the regression net. Renaming/removing config keys is free; one-time migration helpers (~15 LoC) handle the rare case where an entry.options key needs its value carried forward.

**Memory enforcement:** `project_single_user_no_backcompat.md` exists in user memory. Read it. Don't propose mode toggles unless explicitly requested.

---

## Mistake 2: "Remove drain_target_poor / drain_target_very_poor — arbitrage takes over"

**What I proposed:** Since v2 arbitrage handles the "save battery for tomorrow's peak" job, drop the drain_target_poor and drain_target_very_poor sliders entirely.

**Why it was wrong:** The user's question: "What if arbitrage is not enabled?" If arbitrage_enabled=False, the drain targets are the ONLY mechanism preserving charge for poor-forecast days. Removing them turns off all forecast-aware behavior whenever the user disables arbitrage.

**The correction (user direction):** "Wrong on this. What if arbitrage is not enabled? Set effort to high. You're missing things 🙂"

**The right approach:** Drain targets stay as the **fallback path** when `arbitrage_enabled=False`. The new arbitrage path is an OVERLAY that takes precedence only when (`arbitrage_enabled=True` AND `tomorrow_class in poor/very_poor`). On every other code path, drain targets behave byte-for-byte identical to v4.3.4.

**Codified in:** the State Matrix in the plan (under `## Architecture > State matrix`). Implementation MUST preserve the v4.3.4 drain-target rows exactly.

---

## Mistake 3: "Solar will be capped if reserve_level = 80"

**What I proposed:** When in HOLD phase, reserve_level=80 acts as a "hold" so we shouldn't worry about solar over-charging.

**Why it was wrong:** I had the Enphase semantics backwards. The user caught it: "If we hold 80 and the sun wants to charge to 100 before peak, why would we stop that?"

**The correction:** `reserve_battery_level` in Enphase IQ is a **discharge floor**, not a charge ceiling. Setting it to 80 means: "discharge stops at 80%; battery is allowed to go higher." Solar can charge battery to 100% even with reserve=80. HOLD prevents *discharging* below target, never prevents *charging* above target.

**Why it's load-bearing:** This is core to the entire phased model. WAIT/CHARGE/HOLD/DISCHARGE all set `reserve_level` to different values, and every single setting is a discharge floor. If you forget this, the design becomes incoherent.

---

## Mistake 4: "D4 = Saw-tooth charge rate cap"

**What I proposed:** Original D4 was a saw-tooth control loop using `charge_from_grid` switch to cap effective grid draw at 8 kW (instead of the hardware ~20 kW). Goal: prevent grid spikes during arbitrage charging.

**Why it was wrong:** Two reasons, both fatal.
1. **It would flap.** Enphase's `charge_from_grid` is a binary switch (no rate control). When ON, battery pulls at hardware rate ~20 kW. When OFF, ~0 kW. Saw-tooth threshold sits between these two states; hysteresis can't bridge them — system toggles every 5-min decision tick.
2. **It doesn't solve the actual problem.** PEC residential plans don't have demand charges, so "average rate cap" provides no cost benefit. Breaker-tripping concern (the real risk) requires actual peak-rate limiting, which Enphase firmware doesn't expose. Saw-tooth manages averages but instantaneous draw during ON portions is still 20 kW.

**The correction (user direction):** "Mostly ok. Will saw tooth work. If you pause and over charge and then turn it on won't it just do it again and flap?"

**The right approach:** D4 became **arbitrage / EV mutual-exclusion**. The compound-load case (battery 20 kW + EV 7.4 kW + house base 5 kW = 134A on main breaker) is the real panel-stress scenario. Solo battery 20 kW is well within breaker capacity (~83A). Don't run arbitrage AND EV charging simultaneously: when arbitrage's CHARGE phase fires, pause active EVSEs via the existing pause-reason pattern. Auto-resume on phase exit.

**Bonus benefit:** This pattern (`_paused_by_<reason>` set on the controller, with precedence rules) is the same pattern v4.7.x B5 will extend to appliances. Establishing it correctly in v4.5.0 means B5 has a clean integration point.

---

## Mistake 5: "Charge at off-peak start, hold until peak"

**What I proposed:** When tomorrow=poor and arbitrage_enabled, immediately grid-charge at off-peak entry (e.g., 21:00) up to peak_buffer_target=80, then HOLD until peak begins.

**Why it was wrong:** The user surfaced the actual cost-minimization tension:
1. Charging early means committing to a charge based on overnight Solcast alone (no intraday telemetry yet)
2. Holding for many hours means overnight house loads are served from grid (battery refuses to discharge below 80)
3. Forecast freshness benefit goes unused if we charge before sunrise

**The correction (user direction):** "We could technically charge from grid in the morning same day as the peak event we want to displace. That way our forecast is fresher."

**The right approach:** Phased state machine — WAIT during early off-peak (no artificial floor; battery serves loads naturally); CHARGE in late off-peak just before high-rate window starts; HOLD between charge complete and high-rate transition; DISCHARGE during high-rate. This was a major design improvement.

**But then a sub-mistake:** I initially set `lead_time = 120 min` (2 hours) — late charging.

**Sub-correction (user direction):** "Earlier start is better if same day."

**Final approach:** `lead_time = 360 min` (6 hours) default. For same-day target windows, this means CHARGE fires after morning solar telemetry has had time to confirm the forecast (~08:00 summer for 14:00 mid-peak transition). Earlier = safety margin against stalls + benefits from intraday confirmation. Pure-freshness gain from later charging is small once we have intraday data.

---

## Mistake 6: "PEC off-peak ends at 06:00"

**What I assumed:** Standard "overnight off-peak" mental model. Off-peak runs 22:00 → 06:00 weekdays.

**Why it was wrong:** I never checked the actual TOU table. PEC's actual schedule (in `energy_const.py`):

| Season | off-peak | mid-peak | peak |
|---|---|---|---|
| Summer (Jun-Sep) | 00:00–14:00, 21:00–24:00 | 14:00–16:00, 20:00–21:00 | 16:00–20:00 |
| Shoulder (Mar-May, Oct-Nov) | 00:00–17:00, 21:00–24:00 | 17:00–21:00 | none |
| Winter (Dec-Feb) | 00:00–05:00, 09:00–17:00, 21:00–24:00 | 05:00–09:00, 17:00–21:00 | none |

**Summer off-peak runs continuously 21:00 → 14:00 next day — 17 hours.** Same-day morning grid-charge at off-peak rates is fully viable. My "off-peak ends 06:00" assumption killed the same-day-charge idea prematurely.

**Lesson:** Always verify rate tables / TOU schedules from the codebase, never assume. `PEC_TOU_RATES` is the source of truth.

---

## Mistake 7: "WAIT phase needs a drain target floor"

**What I considered:** During WAIT (off-peak, before charge window opens), maintain `reserve_level = drain_target_poor = 30` to "preserve charge in case CHARGE phase doesn't complete."

**Why it was wrong:** WAIT is not protective — CHARGE will refill the battery to peak_buffer_target before the high-rate window regardless of how low SOC drifted during WAIT. Holding a higher floor during WAIT means overnight loads come from grid (at off-peak rate) instead of battery — equivalent grid kWh, but adds an extra round trip vs letting battery serve loads + grid-charging once.

**The correction:** WAIT phase sets `reserve_level = reserve_soc` (just the user's safety floor for outages, e.g., 10%). Battery free to discharge to 10% naturally. SOC drifts based on actual loads minus solar.

**Why this matters mechanically:** Without this, the model has no clear "do nothing" state. WAIT becomes a quiet pseudo-drain-target which contradicts the whole point of the phased model. The right mental model: WAIT = "strategy is dormant; battery operates normally."

---

## Mistake 8: Various "let's add this to v4.5.0" piling-on

Throughout the conversation I (or the user) considered adding to v4.5.0:
- Bayesian-derived peak_buffer_target
- Charge-rate control via `barneyonline/ha-enphase-energy` HACS
- Solar-aware partial top-up (only grid-charge the gap solar won't fill)
- Cycle-wear amortization in ROI math
- Season-variable peak_buffer_target
- Per-high-rate-window economic gate (skip the smaller window)
- Intraday-confirmed dynamic lead time
- Appliance-coordinated arbitrage
- Charge-to-deadline / SOC-target awareness on EVs
- Per-car SOC reading via Tesla API
- EV charging-detection hysteresis filter

**The discipline:** v4.5.0 stays focused on the battery strategy redesign. Every "good idea" above is captured in the **"Advanced topics — deferred to v4.6.x"** section of the plan with a "why deferred" + "what it would unlock" row.

**Why this matters:** The v4.5.0 review surface is already 680 prod / 900 test LoC. Adding 2-3 of these would balloon it past the safe Tier 2 review threshold. Each topic also has dependencies (Bayesian needs v4.5.0 calibration data; rate-control needs HACS integration testing; etc.) that aren't blockers for v4.5.0 but ARE preconditions for the topic itself.

---

## Mistake 9: Ignoring the cost-minimization framing

**What was missing from earlier drafts:** The plan was structured as "battery strategy redesign" without articulating **why** — what is the broader objective, and how does this slot into the larger architecture?

**The correction (user direction):** "We have appliance control coming which will inevitably have to be connected to both EV and battery load control. The nexus point is EC. The ultimate goal is energy cost minimization."

**The right framing:** Added the "Frame: cost-minimization nexus (EC)" section near the top of the plan. Articulates:
- Energy Coordinator is the central decision-maker for every controllable load
- Single objective: minimize total energy cost over time, subject to safety/comfort/forecast-confidence constraints
- v4.5.0 = battery + EV coordination via TOU + Solcast forecast
- v4.6.x = advanced energy-cost optimization topics
- v4.7.x B5 = extends D4's load-coordination pattern to appliances
- v5.0 = config subentries + architectural debt

**Why this matters:** It's the architectural through-line. Without it, each version looks like a discrete project. With it, every version compounds toward the same objective and the integration points are obvious.

---

## Confirmed-good design decisions (don't second-guess these)

These were tested in conversation and approved by the user. Don't relitigate:

1. **Drain targets stay as fallback when arbitrage is OFF.** The state matrix in the plan is authoritative.
2. **Arbitrage gate is forecast class only** (no SOC threshold). `arbitrage_trigger` slider is removed; `arbitrage_target` renamed to `peak_buffer_target`.
3. **Phased state machine: WAIT → CHARGE → HOLD → DISCHARGE.** Determined by SOC + time + gate, not by execution sequence.
4. **`arbitrage_charge_lead_time_min = 360` default.** 6 hours before next high-rate transition. Earlier-bias for safety + same-day intraday confirmation.
5. **Per-chunk lock** (one arbitrage cycle per off-peak chunk). Set on either CHARGE completion or forecast re-check abort.
6. **Forecast re-check at CHARGE entry.** Aborts cleanly if class is no longer poor/very_poor.
7. **D4 mutual-exclusion (not saw-tooth).** Pattern matches existing `_paused_by_*` sets; precedent for v4.7.x B5 appliances.
8. **HOLD = reserve_level set to peak_buffer_target.** Discharge floor only; solar can still charge above target.
9. **Storm/outage paths run BEFORE the arbitrage gate.** Existing precedence preserved.
10. **D3 multi-day Solcast** folded in as a deliverable (was the standalone v4.3.3 plan).
11. **D4 logs flap-protection.** Chunk lock prevents EV pause/resume oscillation if conditions wobble.

---

## Hot-zone code-review focus areas (for the eventual implementation)

When implementing v4.5.0:
1. **State matrix routing in `determine_mode()`.** The 13-row matrix in the plan is the spec. Every row must be implemented. Cross-check via the phase predicate cheat sheet.
2. **`_get_arbitrage_phase` predicate ordering.** First match wins. SOC ≥ target → HOLD; charge_window_open + not_locked + recheck_passes → CHARGE; else WAIT.
3. **Chunk lock reset.** Only on TOU transition INTO off-peak. `_tou.check_period_transition()` is the authoritative signal.
4. **Forecast re-check.** Single call on first WAIT→CHARGE transition per chunk. Don't re-check repeatedly within the chunk.
5. **EV mutual-exclusion timing.** D4 trigger is "arbitrage charging from grid" (i.e., phase=CHARGE), not "arbitrage active" (which includes HOLD).
6. **TOU helper.** `get_next_high_rate_transition` must walk forward across midnight boundaries (essential for winter).
7. **Migration test for `arbitrage_target` → `peak_buffer_target` rename.** User has a saved value; it must carry over.

---

## Reference path through prior planning

To understand context for v4.5.0:
1. `PLANNING_v4.3.3_multi_day_solcast_lookback.md` — superseded; folded as D3.
2. v4.3.0 grid arbitrage hardening (D1 reserve_level fix + D2-D6) — shipped 2026-05-06.
3. v4.3.1 tech debt cleanup, v4.3.2 slider snap-back fix, v4.3.3 EV battery drain SOC slider, v4.3.4 kW/W unit fix — all shipped 2026-05-06 as a chain of small cycles before this redesign.
4. The user's 2026-05-06 reshuffle: v4.5.0 = Battery Strategy Redesign (this); v4.6.0 = Routine Awareness; v4.7.x = B5 Appliance Scheduler; v5.0 = config subentries + arch debt.

Memory references in `~/.claude/projects/.../memory/MEMORY.md`:
- `project_roadmap_decisions_2026_05_06.md` — version order
- `project_single_user_no_backcompat.md` — no mode toggles
- `feedback_post_deploy_ordering.md`
- `feedback_review_bug_visibility.md`
- `feedback_verify_hacs_install.md`
- `feedback_parallel_agent_isolation.md`

---

## What "good" looks like for next session

The next session should:
1. Read `PLANNING_v4.5.0_battery_strategy_redesign.md` end-to-end before implementing.
2. Read this transition doc to avoid re-deriving the corrections above.
3. Open the State Matrix and use it as the routing spec.
4. Use the phase predicate cheat sheet as the `_get_arbitrage_phase` skeleton.
5. Implement deliverables D1 → D8 in order. D1 is the heaviest; everything else depends on its scaffolding.
6. Tier 2 review per CLAUDE.md (Core A + Core B + live validation).
7. Live validation observation period: 14 days. Calibration metric: arbitrage_savings accumulating sanely.

The next session should NOT:
- Propose v1_legacy/v2 mode toggles (Mistake 1)
- Remove drain targets entirely (Mistake 2)
- Treat reserve_level as a charge ceiling (Mistake 3)
- Re-introduce saw-tooth charge rate cap (Mistake 4)
- Set lead_time to 120 min (Mistake 5 — the corrected default is 360)
- Assume PEC off-peak ends at 06:00 (Mistake 6)
- Add a drain floor during WAIT phase (Mistake 7)
- Pile new features into v4.5.0 (Mistake 8)
- Lose sight of cost minimization as the umbrella objective (Mistake 9)
