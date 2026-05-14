# v4.6.2.3 — Review Carry-Overs from v4.6.2.1 + v4.6.2.2

**Date:** 2026-05-14 CDT (same-day close-out of two prior hotfixes)
**Type:** Tier 1 bundle (6 deliverables, all from prior review findings)
**Predecessor:** v4.6.2.2 (Guest mode hardening — deployed earlier same day)

## Problem

Two prior same-day Tier 1 cycles left small carry-over items in BACKLOG, plus one shared shape that bit both: the v4.6.2.1 reviewer flagged it (MEDIUM), and the v4.6.2.2 reviewer flagged a similar 60-second reactivity delay. Bundling so they don't bit-rot, and pioneering a behavioral-test pattern that should have caught the v4.6.2.1 MEDIUM at build time.

## Fix

### D1+D2 — Reload-mid-cycle anchor seeding (BOTH humidity-fan paths)

The v4.6.2.1 max-runtime cap (`_humidity_on_since` anchor) silently disabled itself on options-flow reload while a fan was running. On post-reload eval, if humidity was in the hysteresis band, neither activate nor off branch fired and the anchor never re-seeded.

Now, when the coordinator wakes and observes a humidity fan already ON, both paths seed `_humidity_on_since = now` so the max-runtime cap has a valid reference.

- **Path A (`automation.py`):** new `_fan_is_actually_on(fans)` helper (synchronous `hass.states.get` lookup). Top of `handle_humidity_based_fan_control`: if anchor is `None` and any configured fan is physically on, seed both `_humidity_on_since` and `_humidity_fan_triggered_time` (re-arms the min-runtime gate too).
- **Path B (`hvac_fans.py`):** in the humidity-fan eval block after `h_currently_on` is computed: if `h_currently_on and room_fan.humidity_on_since is None`, seed `humidity_on_since = now`.

Both paths use a monotonic `is None` guard — anchor only ever seeded once per on-cycle.

### D3 — Behavioral test suite for humidity fan

New file `quality/tests/test_v4623_humidity_fan_behavioral.py`. 6 end-to-end tests that drive `handle_humidity_based_fan_control` directly (no source-grep). These would have caught the v4.6.2.1 MEDIUM at build time:

- `test_max_runtime_cap_fires_after_full_window`
- `test_max_runtime_suppression_blocks_immediate_retrigger`
- `test_max_runtime_suppression_clears_when_humidity_drops_below_off`
- `test_hysteresis_no_chatter_at_threshold_boundary`
- `test_reload_seeds_humidity_on_since`
- `test_reload_does_not_seed_when_fan_is_off`

### D4 — Confidence-change reactivity (`presence.py:_handle_census_update`)

v4.6.2.2 review found that `_handle_census_update` only triggered `_run_inference` on count change. A confidence-only upgrade (e.g., `low → high` with unchanged counts) waited up to 60s for the next periodic cycle. Fix: capture `old_confidence` before the field reassignment, extend the change-detection condition.

```python
old_confidence = self._census_confidence
# ...assignments...
if (
    old_count != self._census_count
    or old_unidentified != self._unidentified_count
    or old_confidence != self._census_confidence
):
    self.hass.async_create_task(self._run_inference("census_update"))
```

Two new tests confirm: confidence-only change fires inference; nothing-changed does not.

### D5 — Dead field removal: `_census_source_agreement`

Captured by v4.6.2.2 but never read. Removed cleanly — grep confirms 0 hits across `custom_components/`. Note: the `source_agreement` DB column and SIGNAL_CENSUS_UPDATED payload key are preserved; only the unused coordinator instance field was removed.

### D6 — Test stub drift refactor

`test_v4622_guest_mode_hardening.py::_make_coordinator()` now instantiates a real `PresenceCoordinator(hass=_make_hass(), ...)` instead of the hand-rolled `_Stub` class that re-implemented `_guest_gate_armed`, `_disarm_guest_gate`, `_confidence_at_least`, and `_schedule_guest_persistence_recheck`. Production-code drift is now visible to tests. All 38 pre-existing v4622 tests pass after the refactor.

## Files changed

- `automation.py` — D1 seeding + `_fan_is_actually_on` helper (~15 LoC)
- `domain_coordinators/hvac_fans.py` — D2 seeding (~5 LoC)
- `domain_coordinators/presence.py` — D4 reactivity + D5 dead-field removal (~10 LoC net)
- `quality/tests/test_v4623_humidity_fan_behavioral.py` — new (~489 LoC, 6 tests)
- `quality/tests/test_v4622_guest_mode_hardening.py` — D6 refactor + 2 new D4 tests (~244 net insertions)

## Test count

- v4.6.2.2: 2997 passing
- **v4.6.2.3: 3004 passing** (+7 net)

## Review verdict (Tier 1)

**SHIP** — 0 CRITICAL/HIGH/MEDIUM. 3 LOW (1 docstring polish, 1 cosmetic asymmetry comment, 1 pre-existing carry-over already in BACKLOG). 2 INFO. No fixes required pre-deploy. Reviewer mentally executed 11 scenarios across both paths; all correct.

Review doc: `docs/reviews/code-review/v4.6.2.3_review_carryovers.md`.

## Live validation plan

1. **Reload resilience (humidity fan):** if a humidity-fan room exists and a fan is running, reload that entry's options via Settings → Devices & Services. Within one URA cycle, the new `humidity_on_since` anchor should be seeded (visible if logging at debug). Cap-fire scenario should now work post-reload.
2. **Confidence-change reactivity:** watch URA logs around census events. When `census_confidence` upgrades without count changing, `_run_inference` task should fire within 1–2 seconds (not the prior 60s).
3. **Guest-mode regression:** no GUEST entries for transient unidentified blips — v4.6.2.2's gate behavior unchanged.
4. **Humidity-fan regression:** normal cycles unaffected; cap fires only on stuck-sensor / runaway humidity.

## What's NOT done in this hotfix

Remaining LOWs from prior reviews (deferred to a future polish pass; tracked in BACKLOG.md):

- LOW #3 — Sleep policy clears `_humidity_cap_suppressed` (edge case)
- LOW #4 — HVAC-managing transition leaves stale Path A state (edge case)

The next active cycle is v4.6.3 (anomaly touchpoint migration + behavioral DAO test infrastructure), planned as a phased Tier 2 effort.
