# URA v4.7.6.1 — Labels, Helper Text, and `excess_solar_soc` Number Promotion

**Release date:** 2026-05-29
**Tier:** Tier 1 hotfix (single staff-engineer review)
**Scope:** D1 promote `excess_solar_soc` to a live Number entity with tick-snapshot race mitigation, D2 friendly-name standardization on the Pause/Resume/Floor trio, D3 helper-text rewrites (3-sentence template), D4 per-EVSE label cleanup + dead translation removal, D5 manual updates (corrective footnote + this README + helper-text discipline).

---

## Headline Changes

### D1 — `excess_solar_soc` promoted to a live Number entity

New entity: `number.ura_energy_coordinator_excess_solar_soc`. Default 95, min 80, max 100, step 1, unit %. Slider mode. Live-tunable; effect lands on the next decision tick via a tick-snapshot at the actuation block start (`energy.py::_async_evaluate_dynamic_presets`). Mirrors `FillPrioritySOCNumber` line-for-line including the v4.7.6 fix-up B-M7 `_safe_unsub` double-unsub guard and the v4.7.6 B-M3 tick-snapshot pattern for `_fill_priority_soc`.

RestoreEntity is the canonical runtime store (per `feedback_ura_mirror_pattern`); `entry.options[CONF_ENERGY_EXCESS_SOLAR_SOC]` seeds first install only. New `EnergyCoordinator.excess_solar_soc` property + `set_excess_solar_soc()` setter mirror the v4.7.6 `fill_priority_soc` / `set_fill_priority_soc` pair exactly.

### D2 — Friendly-name standardization (Pause / Resume / Floor)

Three EC-device-page Number entities now read as a coherent trio. `unique_id` and `entity_id` UNCHANGED for HACS/dashboard continuity — only `_attr_name` updated:

| Entity | Old name | New name |
|---|---|---|
| `number.ura_energy_coordinator_fill_priority_soc` | Fill Priority SOC | Pause EV Until Battery SOC |
| `number.ura_energy_coordinator_excess_solar_soc` | (new in D1) | Resume EV at Battery SOC |
| `number.ura_energy_coordinator_ev_battery_drain_soc` | EV Battery Drain SOC | EV Drain-Protection SOC Floor |

### D3 — Helper text (`data_description.*`) rewrites

Four entries in `strings.json` + `translations/en.json` rewritten to the v4.7.6.1 D5.4 template: **one sentence: what triggers the action. Default N%. Range min-max. One sentence: pair/interaction hint OR a See README lookup.** Maximum 3 sentences per entry. Mechanics only — rationale lives in this README.

- `energy_fill_priority_soc` — Pause-until rule, default 80%, range 50–95%, pair with Resume EV at Battery SOC.
- `energy_excess_solar_soc` — Turn-on rule, default 95%, range 80–100%, pair with Pause EV Until Battery SOC.
- `energy_ev_battery_drain_soc` — Deep-floor pause, default 50%, range 5–95%, see README_v4.7.6.1 for rationale.
- `energy_excess_solar_enabled` — Master toggle for both SOC-based rules; off-peak TOU and drain run independently.

### D4 — Per-EVSE label cleanup + dead translation removal

- `garage_a_self_modulates` / `garage_b_self_modulates` now read "Garage A self-modulates (URA re-pauses every cycle)" / "Garage B self-modulates (URA re-pauses every cycle)" in the form-label key.
- Helper text on both rewritten to the user-confirmed wording (smart EVSE/plug hardware list + 1-hour back-off note + EVSE Force-Charge override pointer).
- Dead `l1_plug_self_modulates` keys (from before v4.7.6 fix-up C-H2 split into per-plug fields) DELETED from both `strings.json` and `translations/en.json`. Per-plug dynamic keys (e.g., `<plug_entity_id>_self_modulates`) accept the raw-key label fallback per plan §11 — dynamic per-key translation deferred.

### D5 — Manual updates

- Corrective footnote added to `README_v4.7.6.md` at the `excess_solar_soc` mention clarifying it was config-flow-only in v4.7.6 and promoted to a live Number in v4.7.6.1.
- This README documents the asymmetric-defaults rationale (below).
- Helper-text discipline locked: **helpers carry mechanics, READMEs carry rationale.** Max 3 sentences per `data_description.*` entry.

---

## Asymmetric Defaults Rationale (FP=80, ES=95, Drain=50)

The three SOC thresholds form an **asymmetric dead band**, not three independent knobs. Understanding why they aren't symmetric is the key to understanding why URA behaves the way it does on the boundary.

### The 15-point dead band

```
SOC scale:    0%──────50%─────────────────────80%───────95%───100%
              │       │                       │         │
              │     Drain                    FP        ES
              │     (50)                    (80)       (95)
              │       │                       │         │
              └─ deep floor ─┘                 └ dead band ┘
                  (drain pause)               (no rule fires;
                                               EV runs on TOU)
```

Between FP (80) and ES (95) there is a **15-point band** where neither the fill-priority pause nor the excess-solar turn-on fires. EV charging runs on the normal TOU schedule. This is intentional — it lets the user's actual usage pattern (charge during off-peak, no solar-aware interference) operate undisturbed when the battery is in a healthy middle state.

### Why not symmetric=95/95?

If FP = ES = 95, the system enters a **boundary-oscillation regime**. As SOC ticks from 94.9 → 95.0 → 94.9 within a single decision interval (battery is a noisy sensor), the dispatch flips between "pause EV (SOC < 95)" and "turn EV on (SOC ≥ 95)" repeatedly. The user sees the EVSE relay click in and out every 5 minutes. The Emporia / Tesla Wall Connector hardware logs a thrash pattern. Solar surplus gets fragmented across pause/resume edges and most of it ends up grid-exported rather than landing in the EV.

The 15-point dead band (FP=80 .. ES=95) gives URA room to commit to a decision before the next threshold engages. Once SOC hits 95 and excess-solar kicks in, SOC has to drop ALL the way to 80 before fill-priority pauses again. That's a sustained battery draw, not a noise spike.

### Drain's role as a deep floor behind FP

`DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD = 50` (UNCHANGED in v4.7.6.1 — see §D5.3 of the plan). The drain rule is the **safety net behind the safety net**. It only fires when ALL of:
1. Battery SOC < 50
2. Battery is actively discharging (battery_power < -100W)
3. EV+L1 is actively charging

If fill-priority is working correctly, URA pauses EV at SOC=80 long before drain has anything to do. Drain catches the corner cases:
- Fill-priority is disabled (`excess_solar_enabled = False`)
- Solar forecast was wrong; battery drained below the FP threshold mid-day with the EV still running
- User overrode FP via the EVSE Force-Charge button and forgot to unset

The 30-point gap between FP=80 and Drain=50 is the user's "I'll get to it" margin — there is time to notice and act before drain has to slam the brakes.

### Concrete walkthrough at FP=80, ES=95, Drain=50

| SOC | EV state | What URA does | Why |
|---|---|---|---|
| 30 | charging | Drain PAUSES if battery is discharging | Below Drain floor (50). Last-resort. |
| 30 | charging | Fill-Priority PAUSES if solar forecast healthy | Below FP threshold (80). Primary rule. |
| 60 | charging | Fill-Priority PAUSES if solar forecast healthy | Below FP threshold (80). Primary rule. |
| 60 | paused-by-FP | Idle | URA waiting for SOC to reach 80. |
| 85 | (TOU dispatched) | Runs on normal TOU schedule | Middle band — no solar-aware rule fires. |
| 85 | (off-peak) | Charges per TOU rate | Same. Middle band is intentionally undisturbed. |
| 90 | (TOU dispatched) | Runs on normal TOU schedule | Still in dead band. |
| 95 | charging | Excess-Solar TURNS ON even off-peak | Hit upper threshold; solar surplus available; consume it. |

The middle-band rows are the important ones. v4.7.6 introduced fill-priority so the battery would fill BEFORE the EV gets a turn — but the user explicitly does NOT want URA fighting normal TOU behavior in the middle band. The 15-point gap is what gives URA permission to back off.

---

## "Why your live Drain=80 stays" note

The code default for `DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD` STAYS at 50 in v4.7.6.1 (per plan §11 resolved row + §D5.3). If your live `number.ura_energy_coordinator_ev_battery_drain_soc` reads 80 today, RestoreEntity preserves that across the deploy — the slider's last user-written value is the canonical runtime store, and v4.7.6.1 does not stomp it.

The 50 default affects **fresh installs only**. Your existing install carries your configured value forward unchanged. If you want to align with the new "deep floor" rationale, drag the slider down to 50 manually post-deploy. If you prefer the safety of a higher floor (80), leave it where it is — URA respects your slider.

---

## Pre-Deploy Zero-Bugs Gate

Per `feedback_pre_deploy_zero_bugs_gate.md`:

1. **Conflict markers:** clean.
2. **`py_compile`:** clean for `number.py` and `domain_coordinators/energy.py`.
3. **JSON validity:** `strings.json` and `translations/en.json` parse cleanly. (Added in v4.7.6.1 — broken JSON silently kills HA's translation lookup integration-wide.)
4. **Cycle tests:** all v4.7.6.1 cycle tests pass.
5. **Full suite vs `pre-review-v4.7.6.1`:** zero new regressions vs baseline (4197 / 55 / 14).

---

## Review Trail (Tier 1 — single review)

Tier 1 hotfix: single staff-engineer adversarial review focused on:
1. RestoreEntity round-trip for `ExcessSolarSOCNumber` (incl. B-M7 `_safe_unsub` guard).
2. `data_description` keys land in the correct schema step.
3. Friendly-name strings render verbatim (no translation-key indirection).
4. No regression in v4.7.6 fill-priority behavior.
5. Dead `l1_plug_self_modulates` doesn't break any HA UI lookup.

---

## Deferred Items (Plan §11)

Items the planning doc explicitly defers, still deferred at release time:

- **Per-plug dynamic translation keys** (e.g., `<plug_entity_id>_self_modulates`): out of scope for Tier 1. Per-plug rows render with raw-key labels. Filed for a future cycle — requires either a config-flow translation hook or migration to a list-selector UI.
- **`entity.number.*` translation-key migration for the three EV-SOC Numbers**: explicitly deferred in D2 rationale. `_attr_name` is the source of truth; no benefit from translation-key indirection on this Tier 1 cycle.
- **Switch-entity-card description for `evse_solar_aware_charging`**: D3 omits this — the renamed switch's translation key matches `evse_solar_aware_charging` per `switch.py:722` but the per-switch entity description block in `strings.json` was already added in v4.7.6 for `ev_tou_management` only. If post-deploy UI shows the switch card missing a description, add the block in v4.7.6.2.
- Reviewer B v4.7.6 LOWs B-M5/B-M6 — carried forward from v4.7.6 close-out.
- Dashboard nested-attr rendering of `cooldowns` / `pause_dispatch_state` — dashboard-layer concern.
- NM-trip DST consideration on the day token — stable until the next DST boundary.
