# v4.6.9 — Boot-State Robustness

**Date:** 2026-05-18 CDT
**Tier:** Tier 1 (single review)
**Predecessor:** v4.6.8 (EC TOU Rate Reconciliation + Zone/House Cost Surface)

## Why

Two user-reported papercuts from v4.6.8 deploy day:

1. **Previous Location sensors stuck "Unknown" across HA restart** for any person who was already away when URA last shut down. v4.2.27's in-memory preservation logic was correct, but the values weren't persisted to HA state registry.
2. **Four CM-device buttons greyed out at first boot until a manual coordinator reload** — NM Acknowledge, Clear Bayesian Beliefs, Acknowledge Routine Changes, Anomaly Diagnostic Dump. They check `hass.data[DOMAIN]` for their coordinator and stay unavailable forever because nothing tells HA to re-evaluate `available` once the coordinator registers.

Both fixed with patterns already used elsewhere in URA: `RestoreEntity` for state persistence, dispatcher signal subscriptions for cross-component coordination.

## What you'll notice

- **Person Previous Location sensors hold their value across restarts.** Ezinne/Ziri's `previous_location` no longer resets to "Unknown" when they were already away during the restart.
- **The four CM-device buttons enable within ~30 seconds of URA setup** instead of requiring a manual reload.
- **NM services + button actually work for the first time.** The latent bug fix exposes notification_manager via `hass.data[DOMAIN]["notification_manager"]` — the three service handlers and the button had been silent no-ops since the original 3.6.29 NM cycle.

## Changes

### D1 — RestoreEntity on previous-location sensors
- `PersonPreviousLocationSensor` and `PersonPreviousSeenSensor` (`aggregation.py:4335, 4406`) extend `RestoreEntity`
- New `async_added_to_hass` reads `last_state` from HA registry
- If real-room value (not in sentinel set `{unknown, unavailable, None, away, not_home, home, ""}`), seeds the `PersonTrackingCoordinator` via two new idempotent methods:
  - `seed_previous_location(person_name, location)`
  - `seed_previous_location_time(person_name, time)` — coerces tz-naive to UTC defensively
- Idempotent — never clobbers live data already in `coordinator.data[person_name]`

### D2 — Coordinator-ready dispatcher signals
- New signals in `domain_coordinators/signals.py`: `SIGNAL_NM_READY`, `SIGNAL_BAYESIAN_READY`
- Dispatch sites in `__init__.py`:
  - `SIGNAL_BAYESIAN_READY` immediately after `bayesian_predictor` registration
  - `SIGNAL_NM_READY` immediately after `notification_manager` registration
  - Both use the same try/except pattern as `SIGNAL_DATABASE_READY` (non-fatal on failure)
- 4 button classes get `async_added_to_hass` subscribing via `async_on_remove(async_dispatcher_connect(...))`:
  - `NMAcknowledgeButton` → `SIGNAL_NM_READY`
  - `ClearBayesianBeliefsButton` → `SIGNAL_BAYESIAN_READY`
  - `AcknowledgeRoutineChangesButton` → `SIGNAL_DATABASE_READY` (existing)
  - `AnomalyDiagnosticDumpButton` → `SIGNAL_DATABASE_READY` (existing)
- `_handle_ready` callback calls `self.async_schedule_update_ha_state()` — forces HA to re-evaluate `available`

### D2 bonus — NM latent-bug fix
**Discovered during build.** `notification_manager` was created and assigned to coordinator_manager at `__init__.py:1977`, but **never registered at `hass.data[DOMAIN]["notification_manager"]`**. Four call sites had been reading the dead key for an unknown number of versions:
- `__init__.py:2767` — `handle_acknowledge_notification` service (silent no-op + warning)
- `__init__.py:2777` — `handle_test_notification` service (same)
- `__init__.py:2807` — `handle_test_inbound` service (same)
- `button.py:483` — `NMAcknowledgeButton.available` (always returned False)

One-line fix at `__init__.py:1978` adds the registration. Closes the root cause of the user-reported NM button issue.

## Files changed

| File | Lines |
|---|---|
| `aggregation.py` | +93 (RestoreEntity mixins + restore blocks on 2 sensors) |
| `button.py` | +69 (4 button signal subscriptions + handlers) |
| `domain_coordinators/signals.py` | +8 (2 new signal constants) |
| `__init__.py` | +25 (2 dispatch sites + NM latent-bug one-liner) |
| `person_coordinator.py` | +63 (2 new seed methods, with tz-coercion safety) |
| `quality/tests/test_v4_6_9_boot_state_robustness.py` | +697 (37 tests, all pass) |
| `docs/planning/PLANNING_v4.6.9_*.md` | +198 (new) |
| `docs/BACKLOG.md` | +13 (v4.6.9 closure + v4.6.10 deferrals) |
| `docs/reviews/code-review/v4.6.9_*.md` | +95 (review doc) |

## Tests

- **37 new v4.6.9 tests** in `quality/tests/test_v4_6_9_boot_state_robustness.py` — all pass
- Baseline failure comparison: 56 failed / 14 errors at `pre-review-v4.6.9` baseline, identical post-fix — **zero regressions introduced**

## Review

Tier 1 single-review. **PASS WITH FIXES.**

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | HIGH | `_SKIP_STATES` sentinel set missing `"not_home"`/`"home"` (HA person-entity sentinels) — would store as "Not Home"/"Home" room name | **FIXED** — added to sentinel set in both sensors + inlined test mirror |
| 2 | MEDIUM | `seed_previous_location_time` didn't coerce tz-naive datetime to UTC — downstream subtraction could raise `TypeError` | **FIXED** — added `if time.tzinfo is None: time = dt_util.as_utc(time)` |
| 3 | MEDIUM | Inlined test bodies create drift risk (HA-import env limitation) | **DEFERRED** to v4.6.10 — extract to `person_seed_helpers.py` leaf module |
| 4 | MEDIUM | NM latent-bug fix is a behavior-change surface — services that were silent no-ops now execute | **ACCEPTED** as deploy-checklist live-validation item |
| 5 | LOW | `_SKIP_STATES` is a local var — promote to module constant | **DEFERRED** to v4.6.10 |
| 6 | LOW | Comment typo `self._data` → `self.data` | **DEFERRED** to v4.6.10 |

Full review doc: `docs/reviews/code-review/v4.6.9_boot_state_robustness.md`.

Two new bug classes proposed for `QUALITY_CONTEXT.md`:
- **"Test inlines production logic (drift risk)"** — when test env can't import the production module
- **"Latent registration gap with widespread silent failure"** — `hass.data[DOMAIN]["X"]` read sites without matching writes

## Live validation criteria

Post-deploy verify:
- [ ] `sensor.universal_room_automation_ezinne_previous_location` NOT "Unknown" after HA restart (was BROKEN pre-v4.6.9)
- [ ] `sensor.universal_room_automation_ziri_previous_location` same
- [ ] All 4 CM-device buttons (`button.ura_*`) enable within ~30s of URA setup without manual reload
- [ ] **NM latent-bug exposure:** invoke `service.universal_room_automation.acknowledge_notification` once — no traceback
- [ ] No HA log warnings tied to URA setup ordering
- [ ] No new failures in 24h soak

## Commits

```
2046114 v4.6.9 review fixes: HIGH#1 sentinel + MEDIUM#1 tz coercion + review doc
f842003 v4.6.9: Boot-State Robustness — RestoreEntity + coordinator-ready signals
fe2f57a v4.6.9 planning: boot-state robustness (RestoreEntity + signal subs)
```
