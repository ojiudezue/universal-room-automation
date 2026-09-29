# AUDIT — Gate-8 overshoot stamp kept across Gate-7 fails: are those nudges worse? (2026-09-29)

**Card:** `HVAC-GATE8-OVERSHOOT-STAMP-NOT-CLEARED-1` · **Read-only** (both DBs `mode=ro`, SELECT only).
**Probe:** `scripts/probes/hvac_gate8_stamp_outcomes.py` (`ssh ha "python3 -" < …`), a copy of the M0-P4
replay (`scripts/probes/hvac_w3_m0_p4_gate4_replay.py`) restricted to today's Gate-4 predicate, plus outcome joins.
**Window:** recorder 2026-09-21 04:13 → 09-29 02:00 CDT (2,271 five-minute ticks). Live knobs: sustained samples 2,
detection time 7 min, Gate-7 thresholds 1.5 / 2.2 / 2.2 kW. `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` read first.

## 1. Code claim — VERIFIED

`hvac_override.py` (`check_ac_reset`), `develop`:
- Gate 4 fail clears the stamp — `:4136`.
- Gate 6 fail (not at/below setpoint) clears it — `:4192`.
- Gate 7 fail (`kwh_rate <= zone threshold`, `:4219-4225`) resets `kwh_samples_above_threshold` only; the stamp stays.
- A dispatch clears it — `_handle_overshoot_detected` `:4952` (`zone.last_overshoot_started = ""  # window resets`).
- Kept without clearing: stale kW (`:4201`), Gate 5 lockout / 5b cap, Gate 9 in-flight.

## 2. The P4 "13" was mostly a replay artefact

P4's `run()` never clears the stamp at dispatch; the real code does (`:4952`). Re-running the same replay with and
without the dispatch clear:

| Replay model | zone_1 | zone_2 | zone_3 | Total OLD-only (removed if Gate 7 cleared) |
|---|---|---|---|---|
| P4 as written (no dispatch clear) | 3 | 10 | 1 | 14 (P4 printed 3/9/1 = 13; window now 19 ticks longer) |
| Faithful (dispatch clears, `:4952`) | 3 | 0 | 1 | **4** |

The zone_2 dispatches came only from stamps that outlived a dispatch, which cannot happen in the real code. Of the 4
faithful OLD-only dispatches, 2 match a real `detection_fired` row within ±150 s (zone_1 09-21 12:20, 09-27 22:34), and
both were `effective`. The 2 zone_1 ODU-predicate "10 min early" dispatches in the card belong to the NEW Gate-4
predicate, which M0 stopped. They are not reachable today.

## 3. Outcomes: every real dispatch, labelled from its real stamp age

Each `detection_fired` row stores the real stamp age (`notes overshoot_min`, `:4744`). A dispatch is **CARRIED** if a
replayed tick inside its real stamp window was a Gate-7 fail (Gate 4 passes, temperature at or below setpoint, kW known
and at or below threshold), meaning the proposed fix would have cleared the stamp. Otherwise it is **FRESH**. The
outcome is the next `nudge_evaluated` row within 60 min, plus any `hard_reset_started` within 15 min. Comfort is the
climate `current_temperature` minus the pre-dispatch `target_high` over the 30 min after the dispatch.

| Group | n | Effective | Hard reset after | kWh avoided mean / median | kW before (median) | Stamp age (median) | Max excess °F (median / max) | Minutes > target + 1 °F (total, dispatches) |
|---|---|---|---|---|---|---|---|---|
| CARRIED | 6 (all zone_1) | 5/6 (83 %) | 1 | 0.86 / 0.89 | 1.80 | 20.5 min | 0.5 / 2.0 | 3 min, 1 |
| FRESH | 102 | 97/102 (95 %) | 5 | 1.11 / 1.16 | 2.54 | 10.0 min | 1.0 / 3.0 | 101 min, 7 |

- Fisher two-sided on effectiveness: **p = 0.30**. One ineffective nudge out of 6 cannot be told apart from noise.
- The lower kWh avoided follows the lower draw before the nudge (1.80 vs 2.54 kW). CARRIED dispatches are the ones
  whose draw hovers near the threshold, which is why Gate 7 failed during them. Per kW before, the avoidance is about
  the same (0.48 vs 0.44).
- Comfort was no worse. CARRIED dispatches spent 3 min above target + 1 °F in total, against 101 min for FRESH.
- The labels agree exactly with a plain stamp-age split: the 6 CARRIED rows are exactly the 6 with `overshoot_min > 12`.
- The one ineffective CARRIED nudge was zone_1 09-25 09:45 (1.57 kW before, 1.56 after, threshold 1.5). It escalated
  to a hard reset. It is the same nudge as §10 C1 in the state-of-play doc.

The CARRIED list: 09-21 12:20 (40 min, effective), 09-21 14:50 (30, effective), 09-23 18:21 (21, effective),
09-25 09:45 (20, ineffective → reset), 09-25 15:28 (18, effective), 09-27 22:34 (13.7, effective).

## 4. Verdict — NOT WORSE → close as working as intended

- In 7.9 days, 6 of 108 real dispatches (5.6 %) rode a stamp that survived a Gate-7 fail. All were on zone_1.
- 5 of the 6 were effective. They avoided a similar kWh per kW of draw and caused less discomfort.
- Gate 7 must still pass (2 consecutive samples above threshold) right before any dispatch. A carried stamp only
  shortens the 7-min time-sustained wait. It cannot fire a nudge on low draw.
- Recommendation: close the card with no code change. Keep the finding documented: stale kW, the Gate-5 cap and Gate-9
  in-flight also keep the stamp, and that is intentional.
- **Revival trigger:** any future Gate-4 predicate change, such as the parked ODU-stage wiring. That change would let
  low-draw ticks reach Gate 7 and create early dispatches (P4 (b) = 2). It must re-run this probe, or clear the stamp on
  a Gate-7 fail within its own scope.
- Caveat: n = 6. The data rules out a large effect (for example, carried nudges mostly ineffective or causing
  discomfort). It cannot rule out a difference of about 10 points in effectiveness.
