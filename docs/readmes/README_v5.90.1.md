# v5.90.1 — DP drain-target value-stamp (EVSE-DRAIN-PRECEDENCE-KNOB-80-1)

**Cards shipped:** `EVSE-DRAIN-PRECEDENCE-KNOB-80-1`
**Tier:** 3 (delicate shared-primitive: threads a value through the battery decision path consumed by the EVSE drain-precedence state machine; cost-impacting — a wrong drain floor over-drains the house battery into expensive grid import).
**Branch:** `feature/dp-drain-target-value-stamp` @ `23510f1ca` → merged to develop.

## What this ships

EVSE Drain Precedence (DP) decides whether to pause EV charging so the house battery can drain to a safe off-peak floor before the next peak TOU window. It was draining toward a **stale, re-derived** target (in the common config, coincidentally the static reserve knob ~10) instead of the **composed off-peak drain target** the battery strategy actually clamped and acted on that same tick — Bug Class #63 (coincidental-equality concept collision).

The fix makes DP consume the emitter's value **verbatim**:

- **Value-stamp.** `determine_mode` stamps the post-clamp composed `drain_target` into `_offpeak_drain_branch_target` (`energy_battery.py:5349`), reset to `None` at the top of every synchronous evaluation (`:4638`, entry-reset — `determine_mode` has zero awaits, so this is closed by construction).
- **Capture + thread.** The coordinator captures that value into a local before the first await (`energy.py:5674`) and threads it as a required kw-only `drain_target_soc` into `_dp_decision_tick` / `_run_dp_shadow_eval` (`:4353` / `:4201`); every decision + shadow site consumes it. The old re-derivation is **deleted**.
- **2-tick debounce (INV-DP-DRAIN-1e).** When the stamped target is `None` (drain window left), DP releases the pause only after **2 consecutive** None ticks (`_dp_none_streak >= 2`, `:4460`), resetting on any non-None / non-TRANSITIONED / release tick — kills single-tick oscillation while staying responsive (operator: "2 ticks, I want responsiveness").
- **Blind precedence (C-HIGH-1).** In shadow eval the blind-hold gate is evaluated before the drain-None gate (`:4275`), so a blind signal holds rather than silently releasing.

## Review

Tier 3 — the consolidated fix-up folded review A (reversion-contract mirror + oscillation) and review C (required kw-only rearm of 11 sibling tests, real behavioral anchors replacing hollow source-greps, shadow-precedence reorder). All 4 load-bearing sites are mutation-anchored (each bites its named test, FAIL-on-neuter).

**Orchestrator independent verification (not reviewer trust):** re-grepped all 7 value-stamp anchors; ran my own mutation (`+13`) on the stamp site (`:5349`) → 4 anchors went red, restored clean; full-suite name-diff = **0 new failures** (61 baseline families preserved, +15 new DP tests green; 3 flagged suspects proven pre-existing via develop + isolation runs).

## Acceptance criteria — post-ship (practical: day-0-provable vs organic)

The discriminating observable is `sensor.ura_energy_drain_precedence_state` attribute **`drain_target_soc`**: under the fix it reflects the **composed off-peak drain target** (≥ `reserve_soc`, the strategy's computed floor); the pre-fix bug drained toward the static ~10 fallback.

### Provable day-0 (at restart — no rare event required)
- **Health:** `sensor.ura_battery_strategy` available and well-formed (has `arbitrage_phase`); `sensor.ura_energy_drain_precedence_state` available; zero new URA `ERROR` logs in the first 15 min post-restart.
- **Entry-reset / no cross-restart poisoning:** post-restart the DP state sensor does NOT present a frozen pre-boot HOLD — it reads an idle/fresh state consistent with the current TOU period (discriminates the entry-reset fix from stale carryover).
- **Shape when in a drain-eligible tick:** IF the current tick is drain-eligible, `drain_target_soc` reads the composed target (≥ `reserve_soc`), **not** the static ~10. IF not drain-eligible, DP is idle/HOLD_PRE_EVAL and no drain decision is active — record which state was observed (either is correct).

### Organic (needs an EV-plugged off-peak evening — discriminating observation stated now)
- **Drains to the right floor:** on the first real off-peak drain with the EV plugged in, DP pauses charging and the battery settles at the **composed target** (e.g. ~40), NOT overshooting down to ~10. Discriminator: final resting SOC == composed `drain_target_soc`, not the static fallback.
- **No release flap:** when the target goes `None` (drain window ends), the DP ledger shows the pause released after **2** ticks, with **no** adjacent-tick pause↔release flip-flop.

## Post-deploy validation — Validated 2026-08-25 (day-0, post-restart)

Read from `sensor.ura_energy_coordinator_battery_strategy` after the v5.90.1 restart (HA back up, energy coordinator warmed, config-check valid). The DP state sensor (`sensor.ura_energy_drain_precedence_state`) is disabled-by-default in the registry, so the strategy sensor's attributes were used — they carry both discriminators (`current_offpeak_drain_target` and `evse_paused_by_arbitrage`).

| Criterion | Result | Evidence |
|---|---|---|
| Strategy sensor available & well-formed | ✅ PASS | `state=self_consumption`, `arbitrage_phase=discharge`, coherent `reason` "Mid-peak (summer) — holding charge for peak" (14:41:06 CDT) |
| Boot transient cleared | ✅ as-expected | Held `mode=unknown` / "Envoy unavailable — holding" for ~4 min while the Envoy local integration warmed (Envoy battery entity became available 14:39:41); the next strategy tick resolved to `self_consumption`. Defensive early-return gate, upstream of and orthogonal to this cycle. |
| No new URA ERROR logs | ✅ PASS | error_log + system(ERROR) scans since the 14:35 restart: zero URA ERRORs; no `determine_mode`/`energy_battery`/`energy` traceback. Only pre-existing benign WARNINGs (lock offline, SPAN energy sensors unavailable, HVAC boot-settle, census cameras). |
| Entry-reset / no stale cross-restart DP pause | ✅ PASS | `evse_paused_by_arbitrage: []` post-restart — DP is not carrying a phantom pre-boot HOLD; `current_holds_active: []`. |
| Discriminator present: composed target ≠ static knob | ✅ PASS | `current_offpeak_drain_target: 15` (composed, `target_day_class=excellent`, tomorrow good→15) vs `reserve_soc: 10` (the static fallback the pre-fix bug drained toward). The two values are **provably distinct live**, so a future organic drain can discriminate fix from bug. |

**Deferred to organic (needs an EV-plugged off-peak evening — the discriminating observation is stated so a future session confirms without re-deriving):**
- **Drains to the composed floor, not the static knob.** On the first real off-peak drain with the EV plugged in, DP pauses charging and the battery settles at the composed `current_offpeak_drain_target` (e.g. 15), NOT overshooting to the static ~10. At day-0 DP was not in a drain-eligible tick (mid-peak, `arbitrage_phase=discharge`, no EVSE pause), so the stamp/consume path could not be exercised live — this is the correct "not-in-drain-tick" branch, not a gap.
- **No release flap.** When the target goes `None` (drain window ends), the DP ledger shows the pause released after 2 ticks with no adjacent-tick pause↔release flip-flop (the INV-DP-DRAIN-1e 2-tick debounce).

This closes day-0 validation. The card stays `shipped_organic` until the two organic criteria are observed on a plug-in evening.
