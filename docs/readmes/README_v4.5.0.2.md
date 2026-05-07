# v4.5.0.2 — Hotfix bundle: post-deploy findings

**Date:** 2026-05-07
**Type:** Tier 1 hotfix bundle (5 items + 1 docs class)
**Predecessor:** v4.5.0.1
**Trigger:** Live observations during v4.5.0 deploy on user's 8× IQ Battery 5P system

## Summary

Bundles five focused fixes discovered during v4.5.0 live validation:

1. **`_last_reason` sync on envoy-unavailable path** — prevents self-contradicting sensor state (reason="Arbitrage CHARGE…" + phase="n/a") after an Envoy blip
2. **Orphan `ArbitrageSOCNumber` entity registry cleanup** — removes ghost sliders left in HA's entity registry after the v4.5.0 D2 rename
3. **Defensive grid-import guard** — aborts arbitrage CHARGE if observed grid import exceeds threshold (default 20 kW), preventing breaker trips on undersized panels
4. **Bug Class #31 documentation** — per-unit vs aggregate sensor reads on multi-unit hardware
5. **Switch RestoreEntity investigation** — documented inconclusive findings + two leading hypotheses for the post-deploy switch-reset behavior; no code change

Plus item #3 from the queue (per-unit/aggregate battery_power mapping) was investigated and **closed without code change** — single source of truth in the user's HA install; the apparent 3× understatement was a polling-interval artifact between HA Envoy integration (~60s) and Enphase Enlighten (~real-time) during the breaker-trip ramp.

---

## Items

### 1. Envoy-unavailable `_last_reason` sync

**Bug:** `BatteryStrategy.determine_mode()`'s envoy-unavailable early-return at line 800 mutated `self._arbitrage_phase = "n/a"` and `self._arbitrage_active = False` but did NOT update `self._last_reason`. After a CHARGE tick followed by an Envoy blip, the sensor's `reason` attribute would hold a stale "Arbitrage CHARGE…" string while `arbitrage_phase` showed "n/a" — confusing self-contradicting state.

**Fix:** Set `self._last_reason = "Envoy unavailable — holding (no commands issued)"` (and `self._last_mode = current_mode or "unknown"`) before the early return.

**Discovered:** v4.5.0 deploy at 12:36:16 CDT — user's battery breaker tripped, Enphase comm blipped briefly, sensor showed CHARGE reason + n/a phase for the next tick.

**Test:** `TestV4501EnvoyUnavailableLastReasonSync::test_envoy_unavailable_updates_last_reason` — exercises CHARGE→envoy-blip transition and asserts `_last_reason` changes.

### 2. Orphan entity registry cleanup

**Bug:** v4.5.0 D2 removed `ArbitrageSOCNumber` (the trigger + target sliders) from production code, but HA's entity registry still held the old unique_ids. Result: ghost sliders ("Arbitrage SOC…") persisted on the EC device card in the HA UI even though no Python class was instantiating them — they couldn't be edited, didn't update, but were visible clutter.

**Fix:** Migration helper extended with a separate flag (`arbitrage_soc_orphan_cleanup_done`) so it runs even on installs that already cleared the rename flag in v4.5.0.1. Removes `universal_room_automation_energy_arbitrage_soc_trigger` and `..._target` unique_ids via `entity_registry.async_remove`. Idempotent; no-op on fresh installs.

**Test:** `test_migration_v4502_orphan_cleanup_runs_after_v4501_rename` — exercises the dual-flag path; `test_migration_v4502_idempotent_after_both_flags_set` — confirms re-runs are no-op.

### 3. Defensive grid-import guard

**Bug:** Plan assumed solo battery 20 kW (~83A) was within main breaker capacity. **Reality on user's install:** 8× IQ Battery 5P = 40 kW nominal. Observed 31.9 kW peak grid import during arbitrage CHARGE — tripped panel breaker twice. Strategy can't throttle Enphase's binary `charge_from_grid` switch.

**Fix:** New `_grid_import_guard_triggered()` method on `BatteryStrategy` reads `net_power_w` (already unit-normalized via Bug Class #30 fix in v4.5.0). When grid import (kW) exceeds the configured threshold during a CHARGE tick, the chunk is aborted: `chunk_completed=True`, return WAIT, log warning. Single-shot per chunk — no saw-tooth flap. Threshold defaults to 20 kW; configurable via constructor arg `arbitrage_grid_import_guard_kw` (will become a config-flow form field in v4.5.1).

**Diagnostic surfaces** added to `get_status()`:
- `arbitrage_grid_import_guard_kw` — the configured threshold
- `arbitrage_guard_aborted_at` — ISO timestamp of last abort (None if no abort this chunk)
- `arbitrage_guard_aborted_kw` — net import value that triggered the abort

**Tests:** `TestV4502GridImportGuard` — 7 cases including: charge proceeds below threshold; aborts above; kW unit normalization; chunk reset clears diagnostic; no flap (chunk lock holds even if conditions ease); envoy-unavailable bypasses guard; get_status surfaces.

**Why this isn't saw-tooth (the v4.5.0 plan rejected saw-tooth charge-rate cap):** The plan dropped that idea because Enphase's binary `charge_from_grid` switch can't bridge between ON (~20 kW) and OFF (~0 kW) — saw-tooth would oscillate every 5-min decision tick. The guard here is fundamentally different: it's a **one-shot abort** that locks the chunk and stays in WAIT until the next TOU transition INTO off_peak resets the chunk lock. No oscillation possible within a chunk.

**Why ship this in v4.5.0.2 instead of waiting for v4.5.1's barneyonline rate control:** A trip every time the user runs arbitrage is not acceptable; the user needed to disable Grid Arbitrage entirely until v4.5.1 lands. The guard provides a safety rail so arbitrage stays usable (user just sets the threshold conservatively for their breaker rating).

### 4. Bug Class #31 documentation

Added to `docs/QUALITY_CONTEXT.md`. Sibling of #30 (kW vs W drift); describes silent N× understatement on multi-unit hardware where code reads what it thinks is aggregate but actually gets per-unit. Investigation in this cycle ruled out the bug being present in URA's current battery_power read, but the bug class is real for multi-Envoy / multi-EVSE / multi-inverter installs and worth memorializing.

### 5. Switch RestoreEntity investigation (no code change)

The factory pattern at `switch.py:511-585` looks structurally correct, but several EC switches (Grid Arbitrage, Excess Solar, Grid Import Cap, EV TOU Management) reset to OFF after the v4.5.0 + v4.5.0.1 deploy restart cycle — a regression compared to many prior version deploys.

Investigation inconclusive without a reproducer. Two leading hypotheses documented in the factory's docstring:

- **`is_on` default-return race.** Property returns `self._default` (False) when `_get_energy()` is None during entity registration; HA persists "off"; RestoreEntity restores "off" on next restart; sticky.
- **Reload-mid-setup race.** v4.5.0 D2's migration `async_update_entry` may trigger CM-entry reload mid-startup, entities unload+reload before coord settles.

No defensive fix shipped because (a) both hypotheses lack reproducers, (b) a naive fix could swallow legitimate user toggle-off intent, (c) workaround is one click per switch after a deploy.

Future investigators: capture HA debug logs of restart sequence, observe `is_on` calls + RestoreEntity values + coord-init timing.

---

## Tier 1 Review

| Severity | Item | Resolution |
|---|---|---|
| (no CRITICAL) | — | — |
| HIGH | #3 grid-import guard prevents repeat breaker trips | **Fixed** with one-shot chunk abort |
| MEDIUM | #1 stale `_last_reason` after envoy blip | **Fixed** with one-line + regression test |
| LOW | #2 orphan entity registry entries | **Fixed** with idempotent migration step |
| LOW | #5 switch RestoreEntity reset post-deploy | **Documented** — defer until reproducer + tests |
| INFO | #4 Bug Class #31 docs | **Added** to QUALITY_CONTEXT.md |

**Verdict: READY TO DEPLOY.**

## Tests

- 11 new tests across 2 files
  - `TestV4501EnvoyUnavailableLastReasonSync` — 1 test
  - `TestV4502GridImportGuard` — 7 tests
  - `test_v450_d2_migration` — 3 new migration tests
- All 168 prior v4.5.0 / v4.5.0.1 tests still pass
- **Total: 179 passing**
- 0 new regressions in broader suite (still 57 fail / 14 errors — calibrated baseline)

## Live validation (post-deploy)

1. HACS shows `installed_version: v4.5.0.2`
2. HA error log: NO new "Envoy unavailable" warnings should immediately follow the deploy. If one occurs, sensor reason should now match phase ("Envoy unavailable — holding" + phase="n/a") — no stale CHARGE/HOLD strings.
3. EC device card: ghost "Arbitrage SOC..." sliders should disappear after first restart post-deploy (migration's orphan cleanup step runs once)
4. CM entry options should now contain BOTH `arbitrage_target_rename_migration_done: True` AND `arbitrage_soc_orphan_cleanup_done: True`
5. Sensor `arbitrage_grid_import_guard_kw: 20.0` (default) appears on `sensor.ura_energy_coordinator_battery_strategy` attributes
6. With Grid Arbitrage re-enabled and a poor-forecast day: if grid import ramps over 20 kW during CHARGE, log shows the abort warning and chunk_completed=True. **This should prevent the breaker trip that motivated this hotfix.**

## Deploy notes

- No DB schema changes
- Migration runs at most twice per install (once for v4.5.0.1's rename flag, once for v4.5.0.2's orphan cleanup flag); subsequent restarts short-circuit on the dual-flag check
- HACS download required after deploy.sh per memory `feedback_verify_hacs_install.md`
- **User context:** before re-enabling Grid Arbitrage, verify breaker rating vs the 20 kW default guard threshold. Lower it if necessary for safety.

## Next

- **v4.5.1** — barneyonline charge-rate control + config-flow restructure (paginated form, rate-plan toggle, net-metering branch). Charge-rate control PROMOTED from "v4.6.x deferred topic" to v4.5.1 essential per live findings.
- **v4.5.2** — Test baseline cleanup (drive 57+14 → 0; add CI failure-count guard) — tech debt #0
- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation
