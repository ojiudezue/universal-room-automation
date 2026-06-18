# URA v5.5.4 — Freeze-protection heat_low floor via a central setpoint chokepoint (Tier 3)

Replaces the (now-defeated) single-mode emergency-heat freeze response with a pipe-safety **heat_low floor**: when it's freezing outside, no URA-emitted thermostat range can leave the heat_cool low below 50°F. Self-restoring, no timer.

## What ships

### Central setpoint chokepoint (`hvac_setpoint.py`)
A single `emit_set_temperature(...)` helper that **all 9** `climate.set_temperature` emitters route through (preset-apply, solar-banking ×2, pre-heat, override-compromise, AC soft-nudge + 3 restores). It applies, in one place: **(1) the freeze floor** — raise a sub-50 `target_temp_low` to 50°F when freeze-active; **(2) the deadband invariant** — `high = max(high, low + MIN_DEADBAND)` so a raised low never inverts the range. Future setpoint writers inherit both for free. There is now exactly one `climate.set_temperature` service call in the codebase.

### Freeze-active gate (HC-owned, time/temp-driven, no timer)
`_update_freeze_active()` arms when the best outdoor temp ≤ 35°F, clears at >38°F (hysteresis), fail-open on missing temp. Refreshed **unconditionally every decision cycle** (`hvac.py:897`, in `_run_decision_cycle`) — so the floor is current for every emitter even in observation mode / with guest-mode-actuation off / on first boot. Auto-restores when it warms: the per-cycle re-resolution emits the normal preset.

### Replaces `_set_emergency_heat`
The old freeze response set single-mode `heat` (which v5.5.2's enforcer reverted anyway). Removed. The floor is the new freeze response, consistent with heat_cool ranges. Constants `FREEZE_FLOOR=50, FREEZE_TRIGGER_TEMP=35, FREEZE_TRIGGER_HYSTERESIS=3` in `hvac_const.py` (not config-exposed — parsimony). Defaults tuned for Central TX pipe-safety (50°F never bites normal presets, which hold ≥58°F).

## Review — Tier 3, twice (the protocol earned its keep repeatedly)
- **Single-site build** → Tier-3 4-reviewer: **Review D found the floor leaked** (pre-heat + override-compromise), Review A found a deadband-inversion bug; an operator-directed audit found **9** `set_temperature` sites (not the 2 D found). → rebuilt as the chokepoint.
- **Chokepoint** → Tier-3 4-reviewer: A/B/C SHIP; **Review D found D-HIGH-1** (freeze-active was stale when actuation gates were off — silent no-op in obs-mode/guest-off/boot) + D-HIGH-2 (a thermostat-side away-preset boundary). → D-HIGH-1 fixed (unconditional per-cycle refresh, mutation-verified); D-HIGH-2 operator-accepted as a documented narrow boundary (manual §13 Gap 3).
- Orchestrator independent verification: 9 emitters / 1 service call confirmed; floor-neuter → 9 test failures, deadband-neuter → 2, D-HIGH-1-neuter → 2 (all mutation-anchored). 0 blocking at ship.

Ledgers: `docs/reviews/code-review/v5.5.4_freezefloor_*`.

## Known boundary (accepted, not fixed)
**D-HIGH-2:** the chokepoint governs URA-emitted `set_temperature` ranges, NOT `set_preset_mode`. If guest-mode-actuation is off (URA emits no explicit range) AND a thermostat's OWN device-side away/vacation preset is configured below 50°F, that zone can sit below the floor. Requires a thermostat away-preset literally set <50°F (unlikely). Operator-accepted to avoid a double-writer regression.

## Live Validation — Validated 2026-06-18 (post-restart, v5.5.4 HACS-confirmed)
| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Deploy healthy | PASS | `installed_version: v5.5.4`; config loaded; only the known DB-write-worker startup transient (no new URA errors). |
| L2 | Byte-identical no-freeze behavior | **PASS** | Outdoor 88°F (» 35°F trigger → `_freeze_active` false). `climate.up_hallway_zone_2` + `..._studyb_zone_1` both `heat_cool` with `target_temp_low = 70` (normal summer `home` preset low), **not clamped to 50** — the floor is correctly dormant, no spurious write. |
| L3 | Floor acts at ≤35°F | DEFERRED (winter) | Cannot exercise at 88°F. Mutation-anchored across all 9 emitters + the gate (floor-neuter → 9 test failures; D-HIGH-1-neuter → 2). |

**Verdict:** v5.5.4 deployed healthy; the freeze floor is correctly inert with no freeze (byte-identical, L2 PASS). The floor itself is in-suite authoritative + mutation-verified; real freeze validation deferred to a winter cold snap (≤35°F), where every zone's effective heat_low should read ≥50°F. Cycle CLOSED (pending the seasonal live check).
