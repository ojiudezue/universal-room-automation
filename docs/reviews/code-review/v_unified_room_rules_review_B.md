# AI-ROOM-RULES-TRUST-REPAIR-1 — Review B (async / lifecycle / race)

Branch `feature/unified-room-rules` @ ba03f7568. Base verified: `git merge-base feature/unified-room-rules develop` = 09292d006.
Targeted tests (executor, observability, flow, compiler, v458 gating, cm reload suppression): 143 passed.
HVAC/presence docs not read: the diff touches neither HVAC nor presence producers (it consumes `ura_person_location_change` only).

## Findings

| # | SEV | Site | Scenario | Bug class |
|---|---|---|---|---|
| B1 | MEDIUM | coordinator.py:1293-1305 (`_on_change`), with :1244 | A rule acting on a non-light target whose state settles more than 5 s after the call (cover close, media_player play, vacuum, valve) is booked as a reversal by its own action. HA drops an entity's call context 5 s after it was set (`helpers/entity.py:1235-1240`, `CONTEXT_RECENT_TIME_SECONDS = 5`), so the final `closing -> closed` write carries a fresh Context: not the rule's `ctx_id` and not a URA context. Repro: rule "on exit, close cover.office_shade", shade travel 15 s: `open->closing` (t=0.5 s, ctx match, ignored), `closing->closed` (t=15 s, new ctx) records a reversal and stops the watch. Accuracy for every slow-actuator rule reads near 0 % and the digest reports "undone by hand" for actions nobody undid. Fix: ignore transitional states (`opening/closing/buffering/...`) and changes that move toward the commanded state, or count only a change back toward the pre-fire state. Tests use a fake rig with no context expiry, so they cannot see this. | Event-ordering / timing race (display truth vs ground truth) |
| B2 | LOW | coordinator.py:1218 (`dedup_source_ref=True`) | `source_ref` embeds a microsecond timestamp, so the dedup can never hit, but it still runs `SELECT 1 FROM memory_episodes WHERE source_ref = ?` with no index on `source_ref` (only index: database.py:2015 `(node_id, episode_type, started_at)`). Every rule decision, including every `switch_off` skip, does a full scan of `memory_episodes` inside the single serialized writer. Pass `dedup_source_ref=False`. Table size not measured (Samba mount unavailable during review). | DB write-queue cost (per-row work on the serialized writer) |
| B3 | LOW | coordinator.py:1244-1355 vs __init__.py:6166-6170 | `async_unload_entry` cancels the reversal watches, then awaits further teardown (reconciler, chatter, DB saves) before HA cancels entry background tasks. A `_run_room_rules` task still in its action loop can call `_start_rule_reversal_watch` after the cancel, leaving a state listener and timer on the dead coordinator. Self-heals: the 120 s `async_call_later` expiry stops both. Bounded leak, no action taken. Optional: set a `_rule_watches_closed` flag in `_cancel_rule_reversal_watches` and return early in `_start_rule_reversal_watch`. | Teardown ordering / listener leak (#38 adjacent) |
| B4 | LOW | coordinator.py:1268 | `_rule_light_watch` is keyed by entity. A second rule firing on the same light within 120 s overwrites the first rule's watch, so a reversal is credited to the later rule. Entries are also only pruned when touched. Attribution only. | Shared-state overwrite |
| B5 | LOW | coordinator.py:1071 / 1591 | `_conflict_detected` / `_last_conflicts` are reset on every evaluation by both the inline occupancy path and concurrent signal-task runs, so the conflict binary sensor can be cleared by an unrelated run. Display only. | Concurrent writers to display state |
| B6 | LOW (note) | room_rules_health.py `digest_section` | `_rule_recent` / `_rule_reversals_recent` / `_rule_stats` are RAM only, so the digest's "last 24 h" and the status sensor reset on restart. The nightly trip-wire and accuracy read the DB, so trust paths survive restart. Acceptable; worth one line in ROOM_RULES.md. | Restart resilience (display) |

## Cleared (holds because)

- **Background tasks tracked:** every run uses `entry.async_create_background_task(..., eager_start=False)` (coordinator.py:961, 1201), so unload cancels them. The B-HIGH-2 dispatcher-safety property is preserved for all four signal handlers.
- **D5 bus listener lifecycle:** it is appended to `_unsub_signal_listeners`, rebuilt by `_update_signal_subscriptions` on first refresh and on every options save (`_on_entry_update`, coordinator.py:~2181), and drained on unload (__init__.py:6162-6165). There is no duplicate listener because the rebuild clears the list first.
- **Reversal watch cleanup:** `_stop` unsubscribes the listener and timer and removes itself from `_rule_watch_unsubs`. The expiry `_expire` is a `@callback`. Unload calls `_cancel_rule_reversal_watches` (__init__.py:6166-6170), which an anchor test drives through the real AST-sliced unload body.
- **Event loop:** the LLM call is awaited `ai_task.generate_data` inside `asyncio.timeout(30)` in a config-flow step (rule_compiler.py:560-575). It does not block the loop. `rules_for_entry` is pure dict work, with no I/O.
- **Reload suppression:** `CONF_ROOM_RULES_AI_TASK_ENTITY` is added to both `_NO_LIVE_ATTR_KEYS` and `OPTIONS_RELOAD_SUPPRESS_KEYS` (CM key, read fresh at authoring time). A room-options save of rules still rebuilds the subscriptions.
- **Paused room:** the listeners stay armed while Room Rules is off, by design (INV-R3 records `switch_off`). Cost is one task plus one row per matched trigger, which is low-rate. See B2 for the per-row cost.
- **Switch restore:** `AiAutomationSwitch` RestoreEntity is unchanged. Only the display name changed and the entity id is kept.

## Verdict

**SHIP-with-fix: FIX-REQUIRED on B1 (MEDIUM)** before the accuracy and digest numbers are trusted. B1 does not affect actuation. It corrupts the D6.3 accuracy signal and the D6.5 or digest outputs that the card exists to make trustworthy. B2 is a one-word fix and should land in the same pass. B3-B6 are optional LOWs.

Must-fix: B1, B2 (recommended).
