# URA v5.103.49 — Review-lane batch: quieter stuck warnings, faster restarts, EV flip-flop alert

Four branches built and reviewed earlier, merged together and shipped as one release after a full-suite name-diff on the merged tree. Cards: STUCK-SENSOR-WARNING-PER-TICK-1, SHUTDOWN-CENSUS-DB-WRITES-BLOCK-1, EC-EV-TOGGLE-TRIPWIRE-1, TEST-STRATEGY-REARCH-1 (test-only slice).

## 1. Stuck-sensor warning once per episode (Tier 1, 1 review)
**Problem.** A motion/radar sensor stuck on for hours was correctly ignored, but URA wrote the same "Sensor X stuck on for N hours — ignoring" WARNING on every tick (~3/min per sensor; 483 lines for one sensor in a day), flooding HA's log.
**Fix.** The WARNING is written once per stuck episode, when the daily notification fires; later ticks log at DEBUG. After a same-day restart the boot "Restored stuck-state" line names sensors already reported. Ignoring, notification and per-day latch are unchanged; a still-stuck sensor warns again once after the day rolls over.

## 2. HA restarts no longer stall on URA database writes (Tier 2-DB, 3 reviews)
**Problem.** At shutdown HA stops URA's database writer early; writes arriving after that waited up to 5 minutes for a writer that never came back, so every restart sat out HA's own shutdown timeouts (100 s + 60 s).
**Fix.** Late writes after the writer stops are skipped immediately (they could not be saved anyway); census snapshots stop trying once the writer is gone; a write in progress when the writer stops returns instead of hanging. Deliberate pauses (database cleanup) still queue writes as before. Follow-ups carded under UNLOAD-SYMMETRY-TASK-HYGIENE-1.

## 3. EV charger flip-flop alert (2 reviews; alert-only)
**What.** If URA's battery/EV strategy switches one EV charger on/off more than 2 times within an hour, URA writes one `ev_toggle_tripwire` anomaly and sends one notification per charger per local day. It never changes what URA does with the charger.
**Why.** v5.103.37 removed the night form of the rung-1 / Arbitrage-WAIT loop (11.6 kW charger cycled ~12× in 2 h on 10-01); a daytime residual would otherwise go unnoticed.
**Knobs (module constants, `energy_const.py`):** `DEFAULT_EV_TOGGLE_TRIPWIRE_MAX_PER_H = 2` (≤ 0 disables), `DEFAULT_EV_TOGGLE_TRIPWIRE_WINDOW_S = 3600`. Counts EV chargers only, after the duplicate-command filter; force-charge toggles and manual flips excluded; in-memory (a restart empties the window).

## 4. Test-only: bathroom-exhaust test file collects again
`test_bathroom_exhaust_intelligence_cycle.py` failed to import; fixed so its 66 tests run (~23 previously-failing names gone from the suite baseline). No production code.

## Live validation (prospective)
- Stuck sensor: `system_log` shows the "stuck on" WARNING once per sensor per day, not hundreds; NM still once/day.
- Restart: shutdown completes without "timed out waiting for … log_census" / "_evaluate_nudge_outcome" and without "DB write failed: shutdown timeout"; HA back faster than the ~12 min 10-05 restart.
- EV: 0 `ev_toggle_tripwire` anomaly rows on a normal charging day.
- No URA errors at boot.

## Deploy restart 2026-10-10 (partial — shutdown fix cannot be judged on its own deploy)
- HA restart 19:46:45 → back 19:48:02 UTC (~77 s; the 10-05 restart was ~12 min).
- The shutdown of this restart ran the **old** v5.103.48 code, so its one `coordinator_diagnostics … Error saving baselines: DB write failed: shutdown timeout` (19:47:00 UTC) says nothing about the fix. **The shutdown criteria are judged at the NEXT restart.**
- No `timed out waiting` lines in the shutdown window.
- Remaining checks (stuck-sensor once/day, no ev_toggle_tripwire rows on a normal day) are one-shot reads tomorrow.
