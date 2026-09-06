# v5.96.2 — BLE mop-up: exit-display re-read + naive-UTC day boundary + listener cleanup

**Cards:** EGRESS-EXIT-DISPLAY-REREAD-1, EGRESS-SENSOR-READER-TZ-OVERCOUNT-1 (step 3 "BLE mop-up" of the identity sequence). **Tier:** 2 — 1 review (SHIP) + fix-up (LOWs + a pre-existing HIGH) + orchestrator mutation-verify.

## Fixes
- **Exit display re-read** — after v5.96.1 backfills an exit crossing's `person_id` (~10 min post-crossing), the persons-exited list now refreshes: `SIGNAL_EGRESS_EXIT_BACKFILLED` is dispatched on a successful backfill and the sensor re-reads the row (was showing "unidentified" until restart). Producer `camera_census._backfill_exit_identity`; consumer `PersonsExitedTodaySensor` (dispatcher connect wrapped in `async_on_remove`).
- **Naive-UTC day boundary** — `persons-entered/exited-today` computed the "today" window at LOCAL midnight but string-compared it against the naive-UTC `person_entry_exit_events.timestamp` column, over-counting ~5h of the prior evening at UTC−5. All three reader sites now convert local-midnight → naive-UTC (`local_midnight.astimezone(timezone.utc).replace(tzinfo=None)`), matching the column.
- **Display-shape normalization** — the DB re-read/restore path now produces byte-identical entry dicts to the live append path (`time` key, `person_id or "unidentified"`), so a mid-day backfill can't blank a dashboard field.
- **Listener cleanup (pre-existing HIGH, fixed in-place)** — the two count sensors discarded four listener unsub handles (`hass.bus.async_listen`, `async_track_time_change`) → dead-entity updates on reload; now wrapped in `async_on_remove`.

### Acceptance
- **Test:** 5 anchors incl. two new per-site tz RED-on-neuter (entered + exited count sensors) and the signal-dispatch + re-read anchors.
- **Live:** persons-exited-today reflects a backfilled name without restart; the today counts no longer include prior-evening rows.

## Live Validation — post-restart (to record as `Validated <date>`)
- persons-entered/exited-today counts reset at LOCAL midnight (not 19:00 prior day).
- a backfilled exit shows the named person in the exit list without a restart.
