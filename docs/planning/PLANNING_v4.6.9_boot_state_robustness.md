# PLANNING v4.6.9 — Boot-State Robustness

**Status:** Approved 2026-05-18, ready to build
**Tier:** Tier 1 (single review, no schema change, no DAO change)
**Predecessor:** v4.6.8 (EC TOU Rate Reconciliation + Zone/House Cost Surface)
**Recall hint:** "Resume v4.6.9 — boot-state robustness"

---

## TL;DR

Two user-reported papercuts from v4.6.8 deployment day:

1. **Previous Location sensors stuck at "Unknown"** for persons who were already away when URA last shut down/reloaded. v4.2.27 fixed the in-memory preservation logic correctly, but the values aren't persisted across HA restarts.
2. **Four CM-device buttons greyed out at first boot** (NM Acknowledge, Clear Bayesian Beliefs, Acknowledge Routine Changes, Anomaly Diagnostic Dump) — they check `hass.data[DOMAIN]` for their coordinator and stay unavailable forever because nothing tells HA to re-evaluate `available` once the coordinator registers.

Both fixed by standard patterns already used elsewhere in URA: RestoreEntity for state persistence, dispatcher signal subscriptions for cross-component coordination.

---

## Origin

- Reported by user 2026-05-18 post-v4.6.8 deploy
- Issue 1: "Previous location on whole house device still says unknown if it doesn't see a person at home. It doesn't hold the last see[n] location. I thought we fixed this or are we using the wrong sensor in that location?"
- Issue 2: "Anomaly subsystem, Clear Bayesian beliefs button; all on the CM device - are greyed out until a reload of the coordinators. First bootstrap, uninitialized. Problem."

Live verification 2026-05-18:
- Jaya previous_location: "Jaya Bathroom" (was home this Core uptime) — WORKING
- Oji previous_location: "Dining Room" (was home this Core uptime) — WORKING
- Ezinne previous_location: **"Unknown"** (away across restart) — BROKEN
- Ziri previous_location: **"Unknown"** (away across restart) — BROKEN
- `button.ura_coordinator_manager_clear_bayesian_beliefs.state = "unavailable"` — BROKEN

---

## Deliverables

### D1: RestoreEntity on previous-location aggregation sensors

**Goal:** Persist `previous_location` + `previous_location_time` across HA restarts so a person who was already-away when URA shut down keeps their last-seen room.

**Affected sensors (verified via 2026-05-18 audit):**
- `aggregation.py:4335` `PersonPreviousLocationSensor` (entity ID `sensor.universal_room_automation_<person>_previous_location`)
- `aggregation.py:4406` `PersonPreviousSeenSensor` (entity ID `sensor.universal_room_automation_<person>_previous_seen`)

Both inherit `AggregationEntity, SensorEntity` and read from `person_coordinator.get_person_previous_location(person_id)` + `get_person_previous_location_time(person_id)`. These are aggregation reads of `person_coordinator._data[person_id]["previous_location"]` (in-memory dict, lost on restart).

**Fix:**
1. Both sensor classes extend `RestoreEntity` (mixin already imported in `sensor.py:43`; precedent at `sensor.py:5396` `NMDiagnosticsSensor`)
2. `async_added_to_hass`:
   - Call `await self.async_get_last_state()`
   - If `last_state` exists AND `last_state.state` is a real-room value (not `unknown`, `away`, `unavailable`, `None`, `""`):
     - For `PersonPreviousLocationSensor`: call `person_coordinator.seed_previous_location(person_name, last_state.state)`
     - For `PersonPreviousSeenSensor`: parse `last_state.state` as ISO timestamp and call `person_coordinator.seed_previous_location_time(person_name, parsed_time)`
3. **New `PersonTrackingCoordinator.seed_previous_location(person_name, location)` method:**
   - Idempotent — only seeds if `data[person_name].get("previous_location")` is currently None / "unknown" / "away" / missing (don't clobber live data)
   - Logs at `_LOGGER.debug` what was seeded for which person
4. **New `PersonTrackingCoordinator.seed_previous_location_time(person_name, time)` method:**
   - Same idempotency rule, paired field

### Acceptance Criteria D1
- **Test:** `test_previous_location_restored_after_restart` — simulate sensor with `_state_at_shutdown = "Master Bedroom"`, restart, assert `async_added_to_hass` calls `seed_previous_location("oji", "Master Bedroom")`
- **Test:** `test_seed_previous_location_does_not_clobber_live_data` — coordinator has live `previous_location="Office"`, seed call with `"Stale Room"` is no-op
- **Test:** `test_seed_skipped_when_last_state_is_unknown` — `last_state.state = "Unknown"` → no seed call
- **Test:** `test_previous_seen_time_restored_from_iso_timestamp` — sensor restores `2026-05-18T22:30:00+00:00`, seeded as a timezone-aware datetime
- **Live:** Restart HA. After URA fully sets up, `sensor.universal_room_automation_ezinne_previous_location` should NOT be "Unknown" if there was a real last-seen value in HA state registry from before the restart
- **Live:** No regression for currently-home persons — their previous_location continues to reflect the last room they were in

### LoC budget D1
~50 prod LoC (2 sensor class RestoreEntity additions + 2 new PersonCoordinator methods) + ~80 test LoC

---

### D2: Coordinator-ready dispatcher signal subscriptions on CM-device buttons

**Goal:** Eliminate the "greyed out at first boot until reload" state for four CM-device buttons.

**Affected buttons (verified via 2026-05-18 audit):**

| Class | File:Line | Depends on | Coord-ready signal needed |
|---|---|---|---|
| `NMAcknowledgeButton` | `button.py:453, 481` | `notification_manager` | NEW `SIGNAL_NM_READY` |
| `ClearBayesianBeliefsButton` | `button.py:501, 529` | `bayesian_predictor` | NEW `SIGNAL_BAYESIAN_READY` |
| `AcknowledgeRoutineChangesButton` | `button.py:924, 956` | `database` | EXISTING `SIGNAL_DATABASE_READY` (v4.6.5.3) |
| `AnomalyDiagnosticDumpButton` | `button.py:989, 1023` | `database` | EXISTING `SIGNAL_DATABASE_READY` |

**Fix pattern (per button class):**
1. In `async_added_to_hass`:
   - Import the relevant signal from `domain_coordinators/signals.py` (function-local to avoid circular import — same pattern as `__init__.py:764`)
   - Subscribe via `async_on_remove(async_dispatcher_connect(hass, SIGNAL_XXX_READY, self._handle_ready))`
2. Add `_handle_ready` callback:
   - `self.async_schedule_update_ha_state()` — forces HA to re-evaluate `available`

**New signals to add to `domain_coordinators/signals.py`:**
- `SIGNAL_NM_READY = f"{DOMAIN}_notification_manager_ready"`
- `SIGNAL_BAYESIAN_READY = f"{DOMAIN}_bayesian_predictor_ready"`

**Dispatch sites in `__init__.py` (right after the coordinator is registered in `hass.data[DOMAIN]`):**
- `bayesian_predictor` registration at `__init__.py:1133` → dispatch `SIGNAL_BAYESIAN_READY` immediately after
- `notification_manager` registration site → audit and dispatch `SIGNAL_NM_READY` immediately after
- `SIGNAL_DATABASE_READY` is already dispatched (v4.6.5.3) — buttons just need to subscribe

**Why not just poll `available`?** Buttons don't poll by default (no `_attr_should_poll = True` semantics for stateless action entities). The dispatcher pattern is the standard HA solution and is already in use at `sensor.py` precedents (HVACAnomalySensor at line 7378-7392 per BACKLOG.md reference).

#### Discovered during build — NM latent bug (v4.6.9)

During implementation, `__init__.py` was audited for where `notification_manager` is registered in `hass.data[DOMAIN]`. The audit found it was **never registered**: `coordinator_manager.set_notification_manager(nm)` was called at line 1977, but `hass.data[DOMAIN]["notification_manager"] = nm` was missing entirely.

This means all four callers of the `"notification_manager"` key (`handle_acknowledge_notification`, `handle_test_notification`, `handle_test_inbound` in `__init__.py`, and `NMAcknowledgeButton.available` in `button.py`) always read `None` — the NMAcknowledgeButton was permanently unavailable and the three services always logged warnings. This is the root cause of the user-reported "NM Acknowledge button greyed out" symptom; the dispatcher signal was a secondary fix on top of this.

**Fix applied:** One line added immediately after `coordinator_manager.set_notification_manager(nm)`:
```python
hass.data[DOMAIN]["notification_manager"] = nm  # v4.6.9: register canonical slot
```
`SIGNAL_NM_READY` dispatch follows immediately after.

### Acceptance Criteria D2
- **Test:** `test_clear_bayesian_button_available_after_ready_signal` — instantiate button before predictor registered, assert `available == False`; dispatch `SIGNAL_BAYESIAN_READY`; assert `async_schedule_update_ha_state` was called
- **Test:** `test_nm_ack_button_subscribes_to_nm_ready` — similar shape
- **Test:** `test_acknowledge_routine_button_subscribes_to_database_ready` — using existing signal
- **Test:** `test_anomaly_diagnostic_button_subscribes_to_database_ready` — same
- **Test:** `test_signal_subscription_cleaned_up_on_remove` — verify `async_on_remove` registered the unsubscribe (no listener leak)
- **Live:** After HA restart, the 4 CM-device buttons should be ENABLED within ~30 seconds of URA setup (vs. requiring a manual coordinator reload pre-v4.6.9)
- **Live:** Buttons remain functional — pressing each still invokes the correct underlying action

### LoC budget D2
~40 prod LoC (4 button subscriptions + 2 new signals + 2 dispatch sites) + ~60 test LoC

---

### D3: BACKLOG.md update

- Note v4.6.9 closure of the two user-flagged issues
- File any LOW findings from review for next polish cycle

### Acceptance Criteria D3
- **Verify:** `docs/BACKLOG.md` has v4.6.9 entry, both issues marked SHIPPED

---

## Out of scope

- **Other buttons that don't show the greyed-out pattern** — `ConfigDumpButton`, `ReloadRoomButton`, `ExportDataButton`, `RefreshPredictionsButton`, `_ACRampButton`, `HVACACRampDiagnosticDumpButton` all have different `available` semantics (room coordinator-bound, not CM-device greyed). Not part of this cycle.
- **`SIGNAL_COORDINATORS_READY` master signal** — could be added later as a meta-signal that fires once all 12+ coordinators are registered. v4.6.9 ships with per-coordinator signals; meta-signal is potential v4.6.10 polish if useful.
- **Restoring all person_coordinator state across restart** — only `previous_location` + `previous_location_time` are persisted this cycle. Other fields (current location, previous_seen, transitions) either come from live HA state (current location via geofence) or aren't worth persisting.
- **AggregationEntity / RestoreEntity inheritance order audit** — sticking with the precedent at `sensor.py:5396` and `sensor.py:7943` which use `AggregationEntity, SensorEntity, RestoreEntity` (left-to-right MRO). If there's a hidden gotcha we'll find it in tests.

---

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| `RestoreEntity.async_get_last_state` returns stale data from before a user manually set previous_location | LOW | The seed method is idempotent — only fires when current value is None/unknown/away. Live data wins. |
| `PersonCoordinator.seed_previous_location` called for an unknown person_id | LOW | Seed method does `_data.setdefault(person_id, {})` defensively or skips with debug log |
| Dispatcher signal fires before button is added to hass (race) | LOW | Buttons subscribe in `async_added_to_hass` which fires AFTER the entity is added; if coordinator readiness already happened, button's first `available` poll will return True anyway |
| `SIGNAL_BAYESIAN_READY` dispatch fails during setup | LOW | Pattern at `__init__.py:765` already uses try/except — copy exactly |
| Signal subscriber leak if `async_on_remove` not used | MEDIUM | Acceptance test `test_signal_subscription_cleaned_up_on_remove` covers this |

---

## Tier

Tier 1 — single staff-engineer adversarial review. No schema change, no DAO change, no new coordinator. Mechanical application of existing patterns (RestoreEntity, async_dispatcher_connect).

## Total cost

~90 prod LoC + ~140 test LoC across 2 deliverables. ~1-2 days of work.

---

## Review focus areas

Reviewer should adversarially check:

1. **RestoreEntity idempotency** — does the seed method correctly skip when there's live data? What if `_data[person_id]` was never initialized (cold restart of a person who never had a real location)?
2. **`previous_location_time` parsing** — ISO timestamp restore must handle timezone-aware datetimes; HA state values are strings. Verify the parse uses `dt_util.parse_datetime` and falls back gracefully on parse failure.
3. **`async_added_to_hass` ordering** — does the seed call happen BEFORE the first state poll, or after? Should be before so the first poll already reflects the restored value.
4. **Dispatcher cleanup** — every `async_dispatcher_connect` MUST be wrapped in `async_on_remove`. Verify all 4 buttons do this.
5. **`SIGNAL_NM_READY` dispatch site** — audit `__init__.py` for where `notification_manager` is registered in `hass.data[DOMAIN]`; signal must fire RIGHT AFTER registration, not before.
6. **Bug Class #19 (untracked background tasks):** N/A — no new tasks
7. **Bug Class #21 (tz-naive datetime):** check the timestamp parse uses `dt_util` consistently
8. **Bug Class #34 (function-local imports):** signal imports are intentionally function-local per existing pattern

---

## Ship plan

1. Branch: `feature/v4.6.9-boot-state-robustness`
2. Pre-review tag: `pre-review-v4.6.9`
3. Build D1 + D2 + D3
4. Run `PYTHONPATH=quality python3 -m pytest quality/tests/ -v`
5. Tier 1 staff-engineer review
6. Address CRITICAL/HIGH findings
7. Re-run tests
8. Deploy via `./scripts/deploy.sh 4.6.9`
9. Live validation: restart HA, verify previous_location holds + buttons enabled within ~30s without manual reload
10. Post-deploy review doc at `docs/reviews/code-review/v4.6.9_boot_state_robustness.md`
