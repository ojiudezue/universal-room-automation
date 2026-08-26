# v5.91.2 — HVAC banking auto-release (D1) + arbitrage day-pairing fix + DP very_poor validator

**Cards:** `HVAC-EXCURSION-D1-BANKING-RELEASE-1`, `ARBITRAGE-GATE-D2-OFFBYONE-1`, `DP-VERYPOOR-DRAIN-VALIDATOR-1`
**Tier:** batched — HVAC-D1 (descoped Tier-2, 1 review + orchestrator verify), arbitrage (Tier 2-DB, 3 framing-disjoint + orchestrator mutation verify), dp-verypoor (Tier 1).
**Merges:** `feature/hvac-excursion-d1-only@48b06eaa7` + `feature/arbitrage-gate-d2-offbyone@9403f81f9` + `feature/dp-verypoor-drain-validator@87e047ac` → develop.

## What this ships

Three independent, disjoint-surface fixes batched into one deploy (one restart):

### 1. HVAC banking auto-release (D1)
Banking excursions (pre-cool / pre-heat thermostat borrows) could stay open forever — measured **2 banking rows open, 0 ever ended**. This adds:
- a **periodic auto-release sweep** (`EXCURSION_AUTORELEASE_SWEEP_S=60`) that closes any borrow past its lease via `_auto_return`, and
- a **stale-boot banking release** that closes banking rows left dangling across a restart.
Hardened per review: a `_sweep_running` re-entrancy guard (no double wire-write on a slow Carrier emit), the sweep armed **after** the boot audit (kills a bounded boot double-emit), and a `restore_ok` `:no_entity` discriminator so the validation query can tell a legitimate `manual` skip from a broken entity.

**Descoped:** D2 (setpoint-writer governance gate), D3 (manual-preset recovery), D4 (off-phase ceiling governance) are **parked** (`HVAC-EXCURSION-RESTORE-UNIFIED-1`) — they failed 4 Tier-3 reviews with 3 CRITICALs and need a governance-gate redesign. **Known gap (unchanged from develop):** a `pre_preset==manual` token still closes with `restore_ok=None` and the zone stays manual; D1 does not introduce this (strict improvement — develop dropped the row with no ended-event at all), the fix lives in the parked rework.

### 2. Arbitrage gate day-pairing off-by-one
The arbitrage CHARGE gate paired the peak-anchored target day with a **hardcoded `classify_solar_day_n(2)`** for its multi-day broadening leg — so at offset 0 (target day = today, post-midnight) it compared today against the day-**after**-tomorrow and skipped the actual next day. Fixed at 3 sites (`_recheck_forecast_on_charge_entry`, `_gate_is_open`, and the `get_status` display attr) via `_resolve_target_day(now)` offset + 1 — mirroring the shipped+validated `DRAIN-TARGET-DAY-STALENESS-1` precedent. Byte-identical on the pre-midnight (offset==1) path. Both decision sites + the display attr are mutation-anchored.

### 3. DP very_poor drain-target validator
On a "very poor" solar-forecast night the off-peak drain target came from a hardcoded fallback no slider could change — the accepted-quality set was only `{excellent, good, moderate, poor}`. Adds `very_poor` to the accepted set so the 5th quality target is honored.

## Review
- **HVAC-D1:** 1 read-only adversarial review → SHIP; 2 in-cycle fix-ups; orchestrator verified 151 tests + wire-in anchor.
- **Arbitrage:** 3 framing-disjoint reviews (A correctness+completeness / B cross-coordinator+day-boundary / C test-authority) → **all SHIP**. C independently cleared the concern that 4 modified MultiDay tests were weakened — proved they were asserting the *bug* (only reached the day_3 fixture because of the off-by-one). Orchestrator re-ran the `_gate_is_open` mutation by hand: the named test goes RED, restored clean. Record: `docs/reviews/code-review/arbitrage_gate_d2_offbyone.md`.
- **Pre-deploy gate:** py_compile clean; no conflict markers; combined suite name-diff = 0 new failures (the 12 failures are pre-existing wall-clock / order-pollution / presence families, none in the merged surfaces).

## Acceptance criteria

- **Verify (HVAC-D1):** the auto-release sweep is scheduled in `async_setup` (after the boot audit) and its unsub lands in `_unsub_listeners`.
- **Verify (arbitrage):** at offset 0 with D+1 != D+2 class, `_gate_is_open` reads `classify_solar_day_n(1)` (tomorrow), never `n=2`; at offset 1 the behavior is byte-identical.
- **Verify (dp):** setting the off-peak drain Number on a `very_poor` night live-applies (no hardcoded fallback).
- **Live (HVAC-D1):** on the running instance, banking excursions now **close** — `hvac_excursion_events` shows ended rows with `trigger ∈ {lease_expiry, stale_boot_release}`, not just open rows. (Was 2 open / 0 ended.)
- **Live (arbitrage):** `sensor.ura_energy_coordinator_battery_strategy` `forecast_outlook.d2_class` at offset 0 tracks tomorrow's class, and `arbitrage_gate` decisions use the correct next day.
- **Live (dp):** `sensor.ura_energy_coordinator_battery_strategy` `drain_targets` includes `very_poor` and the accessor honors it.

## Post-deploy validation — (to be written back after restart)
