# DRAFT README section — EC-EV-TOGGLE-TRIPWIRE-1 (ships after EC degraded-data p1)

**What:** an alert-only trip-wire. When URA's battery/EV strategy switches one EV charger on and off more than
2 times within an hour, URA writes one `ev_toggle_tripwire` anomaly row and sends one notification
(per charger, per local day). It never changes what URA does with the charger.

**Why:** v5.103.37 removed the night form of the rung-1 / Arbitrage-WAIT loop that cycled an 11.6 kW charger
~12 times in 2 h on 10-01. A daytime residual is possible and nothing else would notice (code trip-wire instead
of soak watching; operator-approved alarm Q8, 2026-10-03).

**Knobs (rung 1, module constants in `energy_const.py`, change by reviewed code):**
- `DEFAULT_EV_TOGGLE_TRIPWIRE_MAX_PER_H = 2` — toggles allowed per window; `<= 0` disables the trip-wire.
- `DEFAULT_EV_TOGGLE_TRIPWIRE_WINDOW_S = 3600` — rolling window.

**Scope rules:** counts only EV chargers (not smart plugs); counts after the per-charger duplicate filter, so
re-sending the same command does not count; force-charge toggles are excluded; manual switch flips in HA never
reach the counter. In-memory only: a restart empties the window and the day latch.

**Review:** 2 framing-disjoint reviews (A correctness: FIX-REQUIRED -> fixed; B async/lifecycle: SHIP).
Fix-up 1 (2300126d8): notification latch now uses the same local day as the anomaly (was UTC, could drop the
next day's page), EV-specific notification metadata, plain-language text, hollow day-rollover test replaced.
Orchestrator call-neuter drill on the wire-in: 2 tests RED, restored clean.

**Live acceptance (after the deploy that carries it):**
- **Verify (no false alarm):** 0 `ev_toggle_tripwire` anomaly rows on a normal day with ordinary off-peak
  charging (discriminator: a row on a day whose ura_activity_log energy_pool charger rows show <= 2 toggles in
  every hour = false alarm).
- **Verify (real flip-flop):** if a garage EVSE shows > 2 strategy charger_on/off rows in an hour in
  ura_activity_log, exactly one `ev_toggle_tripwire` anomaly + one notification appear that day.
