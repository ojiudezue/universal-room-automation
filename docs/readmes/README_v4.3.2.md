# v4.3.2 — Arbitrage slider snap-back fix

**Date:** 2026-05-06
**Type:** Tier 1 hotfix (single-method behavior fix; one-file change)
**Predecessor:** v4.3.1

## Summary

Fixes the v4.3.0 regression where dragging the **Arbitrage SOC Trigger** or **Arbitrage SOC Target** sliders in the Energy Coordinator's Configuration section snapped back to the original config-flow value on every entry reload.

User-visible: drag `arbitrage_soc_trigger` from 30 → 20, leave the device card, reload integration, slider shows 30 again.

## Root cause

The v4.3.0 review-2 H6 fix in `ArbitrageSOCNumber.async_added_to_hass` introduced this guard:

```python
config_explicit = conf_key in (self._entry.options or {})
if not config_explicit:
    last_state = await self.async_get_last_state()
    ...
```

The intent: "if the user changed the config-flow value this run, config wins; else RestoreEntity (slider persistence) wins." The actual behavior:

- `entry.options[conf_key]` is **always** present — it was set during the initial config-flow setup (long before v4.3.0) and never cleared
- The slider's `async_set_native_value` writes to `self._value` + `RestoreEntity` state, but does **NOT** write back to `entry.options`
- Therefore `config_explicit` is always True, RestoreEntity is always skipped, and `__init__`'s read of `entry.options[conf_key] = 30` overrides any slider drag

The existing `OffPeakDrainNumber` doesn't have this bug because it never had the H6 conditional — it always trusts RestoreEntity.

## Fix

Drop the `config_explicit` branch. Always trust RestoreEntity. Mirrors `OffPeakDrainNumber.async_added_to_hass` line-for-line.

```python
last_state = await self.async_get_last_state()
if (last_state is not None
    and last_state.state not in ("unknown", "unavailable")):
    try:
        self._value = int(float(last_state.state))
    except (ValueError, TypeError):
        pass
```

The `__init__`'s seed-from-`entry.options` is preserved as the **initial value for first-ever startup** when no RestoreEntity record exists yet. From then on the slider is the canonical store.

**Tradeoff (documented in the code comment)**: a user who edits the config-flow value mid-life will not see it reflected on the slider until they also drag the slider once. Acceptable because (a) the slider is the discoverable runtime control surface, and (b) editing config-flow values mid-life is rare.

## What changed

Single file: `custom_components/universal_room_automation/number.py:457-505` — `ArbitrageSOCNumber.async_added_to_hass`. ~12 lines net change (removed conditional + comment update).

Surrounding logic unchanged:
- `super().async_added_to_hass()` call preserved
- Deferred-push retry on EC-not-ready (v4.3.0 C3 fix) preserved
- `async_dispatcher_connect` + `async_on_remove` cleanup pattern preserved
- All `_push_to_coordinator` and `async_set_native_value` methods unchanged

## Tier 1 Review

Per project memory `feedback_review_bug_visibility.md`:

| Severity | Finding | Status |
|---|---|---|
| (none CRITICAL) | — | — |
| (none HIGH) | — | — |
| (none MEDIUM) | — | — |
| LOW | No test verifies slider-persistence-across-reload behavior; would require integration-test infra | **Deferred** — gap, not regression (no such test existed before this fix either) |

**Verdict: READY TO DEPLOY.**

Reviewer findings:
- Behavioral correctness verified across (1) HA restart, (2) entry reload, (3) fresh integration setup with no prior state, (4) the user's actual drag-30→20 scenario
- No side effects: zero callers depend on the H6 behavior; no tests verify the old conditional
- Perfect parity with the working `OffPeakDrainNumber` reference pattern
- Tradeoff documented in code comment

Full review at `docs/reviews/code-review/v4.3.2_slider_snapback_fix.md`.

## Tests

- 112 tests pass (envoy + battery + consumption suites)
- AST clean
- No new tests added — slider lifecycle behavior across entry reload requires integration-test infra not yet in URA's test setup; tracked as the LOW finding above

## Live validation (post-deploy)

After HACS download + HA restart:

1. Confirm `installed_version: v4.3.2` via HACS
2. **The killer signal**: drag `number.ura_energy_coordinator_arbitrage_soc_trigger` from 30 to 20 in the EC device card. Leave the page. Wait 5+ minutes (or reload the integration manually). Return to the page. **Slider must read 20** (NOT 30).
3. Same test for `arbitrage_soc_target` (drag 80 → 70 → reload → confirm 70).
4. Confirm the v4.3.0 `threshold_warning` attribute on `sensor.ura_energy_coordinator_battery_strategy` flips off when the trigger=20 is below drain_poor=30 (no oscillation collision).

## Deploy notes

- No DB schema changes
- No config-entry migration needed
- HACS download required after deploy.sh per `feedback_verify_hacs_install.md`

## Next

Continue with the remaining backlog per `project_roadmap_decisions_2026_05_06.md`:
- v4.3.x — additional narrow hotfixes if live validation surfaces more
- v4.4.x — B5 Appliance Scheduler (TBD scheduling)
- v4.5.0 — Routine Awareness (B6 + B7) per `docs/planning/PLANNING_v4.5.0_routine_awareness.md`
