# v4.3.3 — EV Battery Drain SOC runtime slider

**Date:** 2026-05-06
**Type:** Tier 1 hotfix (single new entity + 2 EC accessors)
**Predecessor:** v4.3.2

## Summary

Surfaces the previously-config-flow-only `energy_ev_battery_drain_soc` threshold as a runtime-adjustable slider in the Energy Coordinator's Configuration section. Drag-to-tune from the device card alongside the off-peak drain + arbitrage sliders shipped in v4.2.10 + v4.3.0.

User found the existing threshold (default 50%) was too low for their setup — wanted EV charging to pause when home battery is below 80%. Today they'd have to navigate config flow → Energy form → field → save → reload. Now: drag a slider on the EC device card; takes effect within 5 min.

## What changed

### New entity

`number.ura_energy_coordinator_ev_battery_drain_soc`
- Range 5–95% (slightly wider than the 10–90 config-flow range so the slider stays useful for prosumer tuning)
- Step 5%, default 50%
- `entity_category=CONFIG` so it appears in the Configuration section of the EC device card
- `RestoreEntity` for persistence across restarts and entry reloads
- Mirrors the post-v4.3.2 `ArbitrageSOCNumber` pattern: always trusts RestoreEntity; **no** `config_explicit` branch (avoids the snap-back regression v4.3.2 fixed)

### EC API additions (`domain_coordinators/energy.py`)

```python
@property
def ev_battery_drain_soc(self) -> int: ...

def set_ev_battery_drain_soc(self, value: int) -> None: ...
```

Slider write → `set_ev_battery_drain_soc(value)` → mutates `self._ev_battery_drain_soc`. The existing `EVChargerController.determine_battery_drain_actions` calls (`energy.py:1872, :1897`) read this value live each tick, so changes take effect on the next decision cycle.

## How the rule works (unchanged from v4.2.17)

EV charging is paused when **all three** are true:
1. EVSE is currently charging
2. Home battery is discharging > 100W (battery actually being drained)
3. SOC is below the threshold

Resumes when:
- Battery stops discharging (e.g., reserve holds, grid takes over), OR
- SOC recovers to threshold + 5% hysteresis (solar refill)

Manual override (user turns charger back on during pause): 1-hour cooldown before URA may pause again.

## Tier 1 Review

Per project memory `feedback_review_bug_visibility.md`:

| Severity | Finding | Status |
|---|---|---|
| (none CRITICAL) | — | — |
| (none HIGH) | — | — |
| (none MEDIUM) | — | — |
| LOW | Module version comment in `number.py:3` says v4.3.2 | **Auto-fix** — `deploy.sh` stamps v4.3.3 |
| LOW | Range expansion (config-flow 10–90 → slider 5–95) is intentional; could use a docstring note | **Deferred** — minor nit |
| LOW | No test coverage for slider lifecycle (restore/deferred-push) — same gap as `ArbitrageSOCNumber` | **Deferred** — opportunistic; same gap exists for the older sliders |

**Verdict: READY TO DEPLOY.** All proven patterns from prior cycles. Zero deviations from the post-v4.3.2 lifecycle.

Full review at `docs/reviews/code-review/v4.3.3_ev_battery_drain_slider.md`.

## Tests

- 112 tests pass (no changes needed; consumer paths unchanged)
- AST clean for Python 3.9

## Live validation (post-deploy)

After HACS download + HA restart:

1. Confirm `installed_version: v4.3.3` via HACS (per `feedback_verify_hacs_install.md`)
2. Confirm new entity exists: `number.ura_energy_coordinator_ev_battery_drain_soc`
3. Slider value should match whatever the user previously set (50 default, OR 80 if they did the v4.3.2-era config-flow update earlier today)
4. Drag slider to 80, leave page, reload integration, return — slider must persist (not snap back). Same persistence guarantee as v4.3.2's arbitrage slider fix.
5. With battery at <80% AND discharging AND EV charging: confirm `paused_by_battery_drain` shows the EVSE id and EV pauses within ≤5 min. Log message: `"EV battery drain: pausing garage_a (battery=-XXXW, SOC=YY% < 80%)"`

## Deploy notes

- No DB schema changes
- Config-flow value remains the initial seed for first-ever startup; subsequent slider drags persist via RestoreEntity
- Manifest stamped to v4.3.3 by deploy.sh
- HACS download required after deploy.sh per `feedback_verify_hacs_install.md`

## Next

Per `project_roadmap_decisions_2026_05_06.md`:
- **v4.3.4** — multi-day Solcast forecast lookback per `docs/planning/PLANNING_v4.3.3_multi_day_solcast_lookback.md` (rename to v4.3.4 when work begins)
- **v4.4.x** — B5 Appliance Scheduler
- **v4.5.0** — Routine Awareness with reconciled AnomalyEvent foundation
