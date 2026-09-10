# v5.100.7 — Energy SOC-ladder cross-validation + primary-SOC staleness gate

**Type:** Energy correctness (guardrails, not a strategy change). **Tier:** Tier-3 — 3 framing-disjoint
reviews + fix-up + orchestrator mutation-verify. Cards: `EC-SOC-LADDER-XVALIDATE-1`,
`FROZEN-POWER-READ-STALENESS-CLASS-1`.

## What shipped
- **SOC-ladder cross-validation.** The operator-set SOC thresholds (reserve, the 5 drain buckets incl.
  **very_poor**, peak_buffer_target, fill_priority, excess_solar, ev_battery_drain, inclement floor) are
  now checked for sane ordering — at config-flow **save time** (rejects an inverted ladder with a named,
  translated error) AND at **runtime** (a live Number-slider inversion emits a rate-limited
  `threshold_ladder_violation` anomaly). Prevents the pause/resume oscillation an inverted band causes.
- **Primary-SOC staleness gate.** The primary battery-SOC reads (`soc_envelope`, `envoy_available`) now
  reject a frozen-valid value via the shared `_read_fresh_float` helper (`DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S=300`,
  kill-switch at 0), same class as ENVOY-PRODUCTION-STALE-1. **MED-2 (operator-confirmed):** `net_power`/
  `battery_power` are deliberately NOT gated — respecting the prior Tier-3 decision (energy_const.py:339-345);
  we did not do the work to overturn it.

## Review outcome
3 reviews: B SHIP; A + C FIX-REQUIRED. Found: the `very_poor` drain bucket excluded from the ladder
(A-HIGH-1), the **runtime** ladder wire-in untested — 4th cycle of that pattern (C-HIGH-1), the config-flow
save-gate untested (C-HIGH-2), missing translations, a silent-except swallow. Fix-up (commit f37ca92e1)
addressed all + added 12 tests (30 total). **Orchestrator independently re-mutated the two load-bearing
sites** — dropping the runtime kwargs → 5 wire-in tests RED; neutering the very_poor rule → 3 RED — restored,
30/30 green.

## Live validation — acceptance criteria
- **L1:** restart clean, config valid.
- **L2 (save gate):** submitting an inverted ladder (e.g. `fill_priority > excess_solar`) in the Energy
  options step is rejected with a readable error on the slider; a valid/equal ladder saves.
- **L3 (runtime guard):** a live-slider inversion emits one `threshold_ladder_violation` anomaly (rate-limited).
- **L4 (staleness):** a frozen primary-SOC entity is treated as stale (envelope engages / envoy_available False), same as unavailable.

_Validated <date> — filled in post-restart._
