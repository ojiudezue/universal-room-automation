# PLANNING — Music Following Audit + High-Level Plan

**Author:** ura-planner
**Date:** 2026-07-02
**Status:** AUDIT + PLAN (no code changes)
**Scope:** Music-following capability — the feature that transfers music playback between rooms when a tracked person moves.

---

## Institutional context verified

### Code locations surveyed (read end-to-end)
- `custom_components/universal_room_automation/music_following.py` (1063 lines) — the standalone `MusicFollowing` class: transition listener, transfer state machine, platform-specific transfer methods (Sonos/Linkplay/WiiM/Denon/MASS/generic), volume save/restore, verification+nudge, group cleanup, diagnostic stats.
- `custom_components/universal_room_automation/domain_coordinators/music_following.py` (586 lines) — the `MusicFollowingCoordinator` wrapper: BaseCoordinator lifecycle, AnomalyDetector wiring (`transfer_success_rate`, `cooldown_frequency`), safety/security/arrival signal handlers, config surface, teardown.
- `custom_components/universal_room_automation/transitions.py` (relevant sections around L200-250, L569-640) — `TransitionDetector` that emits transitions to MusicFollowing; ping-pong suppression happens HERE (not in MF), and suppressed transitions are NOT notified to listeners.
- `custom_components/universal_room_automation/__init__.py` L1902-1915, L2163-2210, L3583 — setup wiring: `MusicFollowing` initialized before Coordinator Manager registers `MusicFollowingCoordinator`; all tracked persons auto-enabled; unload pops `music_following` key.

### Greps run + results (for every proposed addition below)
- `music|media_player|follow` (case-insensitive) across `custom_components/universal_room_automation/` — located the two `music_following.py` files (standalone + coordinator), no third implementation.
- `MF_|MUSIC_|CONF_MF|CONF_MUSIC|MUSIC_TRANSFER` in `const.py` — full existing constant surface catalogued (see appendix). Any REUSED marks below cite these.
  - `CONF_MUSIC_FOLLOWING_ENABLED` (L84) — top-level enable
  - `CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED` (L1042) — CM registration gate
  - `CONF_MF_COOLDOWN_SECONDS` / `_PING_PONG_WINDOW` / `_VERIFY_DELAY` / `_UNJOIN_DELAY` / `_POSITION_OFFSET` / `_MIN_CONFIDENCE` / `_HIGH_CONFIDENCE_DISTANCE` (L1167-1173) — tuning knobs
  - `CONF_MUSIC_ON_HAZARD_STOP` / `_ON_ARRIVAL_START` / `_ON_SECURITY_STOP` (L1524-1526) — cross-coordinator gates
  - `CONF_MUSIC_ANOMALY_SENSITIVITY` (L1130)
- `SIGNAL_PERSON_ARRIVING|_on_person_transition|ping_pong` across component — confirmed the two entry points into MF (`TransitionDetector` callback + arrival signal handler) are the only ones; ping-pong suppression in `transitions.py:231` short-circuits BEFORE MF sees the transition.
- Tests: `quality/tests/test_music_following.py`, `quality/tests/test_music_following_coordinator.py` — inline-logic replicas (no HA import), cover ping-pong, confidence, cooldown, winner rules, position offset.

### Prior planning docs consulted
- Directory glob `docs/planning/*music*` / `*mf*` / `*follow*` — **no dedicated MF planning docs exist**. All MF work has landed inside cross-cutting cycles (v3.6.19-v3.6.27 hardening, v3.22.0 signal integration, v4.6.3/4.6.5.x anomaly-metric fixes). This audit is the first standalone MF planning doc.
- `docs/planning/PLANNING_v3.6*` — none present in current tree.

### Memory bodies pulled
- `MEMORY.md` index scanned — no MF-specific memory entries. The "silent-actuator failure class" entry (2026-07-01, v5.7.2) is directly relevant: dead media_player = URA `turn_on`/`play_media` calls silently no-op. `sensor.<room>_unavailable_entities` only tracks INPUT sensors, not actuator media_players.

### Design docs read
- `docs/Coordinator/` glob — **no `MUSIC_FOLLOWING.md` design doc exists.** Design intent lives only in docstrings + planning-doc history. Gap noted as a deliverable below (D0).

### QUALITY_CONTEXT bug classes reviewed for relevance
- #7 stale data source, #22 enum mismatch, #23 observation mode gating (already applied at coordinator handlers), #32 restore-persistence, #34 dispatcher-import UnboundLocalError, #50 substrate sub clobbering, #52 RestoreEntity unavailable-coercion, #53 computed-but-not-consumed. Applied to findings below where a pattern match exists.

---

## Feature summary (as-shipped)

**Purpose:** When a tracked person transitions rooms with sufficient confidence, transfer the source room's playing music to the target room's media_player. Preserve volume, use native multiroom join for same-platform, fall back to `play_media` for cross-platform. Fade source, verify target, unjoin source after delay.

**Trigger surface:**
1. `TransitionDetector` calls `MusicFollowing._on_person_transition(RoomTransition)` (primary path — but only for transitions that pass ping-pong suppression in `transitions.py:231`).
2. `SIGNAL_PERSON_ARRIVING` handled by `MusicFollowingCoordinator._handle_person_arriving` — logs only, **no actuation** (stub).
3. `SIGNAL_SAFETY_HAZARD` / `SIGNAL_SECURITY_EVENT` with severity=critical → `_stop_all_playback()`.

**Gates (in order):** same-room guard → enabled_persons membership → `MIN_CONFIDENCE` (0.6) → BLE distance (`_mf_high_confidence_distance`, 8ft) → concurrency lock → per-person+target cooldown (8s) → source-playing check → winner rules (target not already playing) → transfer → verify → group cleanup.

---

## PART 1 — Correctness issues

### C1 (HIGH) — Silent no-op on unavailable target media_player (Bug Class: silent-actuator)
**Location:** `music_following.py` `_execute_transfer` L316-350 checks `from_state` but the target `to_state` only checked for `state == STATE_PLAYING` (winner rule). If `to_state is None` or `unavailable`, the code proceeds through `_transfer_media`, calls `media_player.play_media` / `join` / `transfer_queue` against a dead entity, all service calls succeed silently or raise into a caught Exception, `_verify_transfer` reads back `state=None|unavailable != STATE_PLAYING`, records `unverified`, restores source volume. **User-visible:** music "disappears" from source without appearing in target. This is the exact silent-actuator pattern documented in the 2026-07-01 memory entry and CLAUDE.md Troubleshooting.

**Fix direction:** Pre-flight availability check on `to_player` (state exists AND state not in `("unavailable", "unknown")`). Record a new stat `target_unavailable`. Do NOT fade source. Surface via a new `sensor.music_following_last_skip_reason` or extend `_last_transfer_result`.

### C2 (HIGH) — Diagnostic listener callback is sync-in-async-context; failures swallowed
`music_following.py:172-199` (`_record_stat`) calls each listener in a bare `try/except: pass`. The coordinator's listener is `_on_transfer_outcome` (sync), which schedules `hass.async_create_task(...)` — fine — but any exception inside the sync listener body **before** the task is created is silently discarded. Ping-pong-suppressed / low-confidence / winner-blocked stats never trigger anomaly emission because `_record_stat` is only called from `_execute_transfer`; **there is a partial gap**: ping-pong suppression happens in `transitions.py` BEFORE MF ever sees the transition, so `ping_pong_suppressed` counter in MF is always 0 despite being in `_transfer_stats`. Bug class match: #53 computed-but-not-consumed (counter defined, never incremented, misleads baseline).

**Fix direction:** Either remove `ping_pong_suppressed` from MF stats or wire a `transitions.py` hook that increments it on suppression. Same-room transitions (`from_room == to_room`) also silently `return` without stat.

### C3 (HIGH) — Race: concurrency lock uses `.locked()` check + `async with lock` (TOCTOU)
`music_following.py:279-286`:
```
if self._transfer_lock.locked():
    ...record cooldown_blocked; return
async with self._transfer_lock:
```
Between the `.locked()` check and the `async with` acquire, another coroutine can release; not harmful here (would just proceed). But the reverse — two transitions arriving during the same event-loop tick, both see `locked()==False`, both try `async with`, second waits. The second is NOT recorded as blocked and will fire a full transfer AFTER the first — likely into a target that is now playing the just-transferred content (blocked by winner rule) or into an unrelated target (stale transition). The correct pattern: `try: await asyncio.wait_for(lock.acquire(), timeout=0)` or check the transition timestamp freshness before acquiring.

**Fix direction:** Add "transition age" check inside the lock; if elapsed > N seconds, skip (record `stale_transition`). Also record `queued_blocked` when a second transition waited for the lock.

### C4 (MEDIUM) — `_saved_volumes` and `_active_groups` leak across teardown
`domain_coordinators/music_following.py::async_teardown` cancels `_pending_tasks` and saves anomaly baselines but does **not** clear the underlying `MusicFollowing`'s `_saved_volumes`, `_active_groups`, `_cleanup_tasks`, `_last_transfer_time`, `_last_transfer_target`. On reload (config-flow options change), the standalone `MusicFollowing` instance is **kept** in `hass.data[DOMAIN]["music_following"]` (only cleared on full unload L3583). If cleanup tasks from a prior instance are running when the coordinator is torn down mid-cleanup, they still call `hass.services.async_call("unjoin", ...)` against entities that may now be reconfigured. Bug class match: untracked-background-tasks in the standalone class.

**Fix direction:** `MusicFollowing.async_teardown()` that cancels `_cleanup_tasks`, clears `_saved_volumes`, `_active_groups`. Coordinator calls it from its own teardown.

### C5 (MEDIUM) — Enable-for-person state lost on reload
`__init__.py:1913-1915` calls `enable_for_person` for all `tracked_persons` at setup. On config-flow reload of the CM entry, the coordinator is torn down and re-registered, but the standalone `MusicFollowing` singleton is preserved with existing `_enabled_persons`. If a person was removed from tracked_persons via options-flow, they remain in `_enabled_persons`. Reverse: newly added persons aren't enabled until full HA restart. Bug class match: reload-symmetry / stale-state.

**Fix direction:** Options-flow update listener that re-syncs `_enabled_persons` against current tracked_persons.

### C6 (MEDIUM) — `_get_room_player` HA Area lookup picks alphabetical, not configured/preferred
L638-641 (`music_following.py`) — when multiple media_players exist in an HA area, picks first alphabetically. This is a livability issue but also correctness-adjacent: on a house with `media_player.master_amp` + `media_player.master_tv`, alphabetical picks the amp for music which may be right — but on a bedroom with `media_player.bedroom_tv` + `media_player.bedroom_sonos`, TV wins. Logs guidance but silently mis-picks.

**Fix direction:** Prefer entities on known multiroom platforms (Sonos/WiiM/Linkplay/MASS) over generic; log a WARNING (not INFO) when ambiguous.

### C7 (MEDIUM) — `_handle_person_arriving` is stub but ships as INFO
Coordinator `_handle_person_arriving` (L449-492) logs "would start music" but never actuates, even when `CONF_MUSIC_ON_ARRIVAL_START` is enabled. Truth-in-advertising bug: the config toggle exists in options-flow but does nothing. Bug class match: #23 observation-mode gate misused (feature is permanently in observation mode). Either remove the toggle or implement — currently a foot-gun for users who enable it and don't understand why music doesn't start.

### C8 (LOW) — `MIN_CONFIDENCE` set on class attribute at setup, not instance
`domain_coordinators/music_following.py:121`:
```
mf.MIN_CONFIDENCE = self._min_confidence
```
`MIN_CONFIDENCE` is defined as a class attribute (L92 in standalone). Assignment to `mf.MIN_CONFIDENCE` creates an instance attribute that shadows the class attribute for THIS instance. Fine — but note also `mf._mf_high_confidence_distance` (private attribute injected). Fragile pattern. Bug class match: undocumented mutation of a private surface.

### C9 (LOW) — `_pending_tasks: set[asyncio.Task]` on coordinator but `_cleanup_tasks: list` on standalone
Two divergent patterns for background-task tracking. `_cleanup_tasks.remove(t) if t in ...` (L497) is O(n) list scan. Standardize to `set` and use `discard`.

### C10 (LOW) — Restart resilience: no persistence of last-transfer state
`_last_transfer_time` / `_last_transfer_target` (cooldown state) live in RAM only. On HA restart within the 8s cooldown window, a duplicate transfer can fire. Low impact (8s window), but the fix is trivial (use `RestoreEntity` or write to the anomaly DB).

### C11 (LOW) — `_transfer_stats` daily reset is timezone-naive relative to `dt_util.now()`
L174 `dt_util.now().strftime("%Y-%m-%d")` — uses HA-configured timezone, correct. But the "day boundary TOU" cycle (v4.7.29) showed the codebase has repeatedly gotten day boundaries wrong. Add a test.

---

## PART 2 — Livability improvements

### L1 (HIGH livability) — Sleep / night gating absent
There is no gate against transferring music while `HouseState.SLEEP` or `home_night`. A partner walking to the bathroom at 3am while the other has music playing on a bedroom speaker → MF fires a `join` on the hallway speaker, blasting audio. The `_handle_safety_hazard` pattern for observation-mode gating already exists — sleep gating should mirror it. **Suggested behavior:** during SLEEP, suppress ALL transfers (record `sleep_suppressed`); during `home_night`, allow transfers only if the target room is the same person's dwell room.

### L2 (HIGH livability) — Guest / unidentified-person behavior undefined
`_enabled_persons` is populated from `tracked_persons` only. When an unidentified person moves through, no transfer fires — good default. But when a HOSTED guest is in a bedroom with music playing and the owner walks past, the owner's transition can pull the guest's music into the hallway. **Suggested behavior:** don't transfer OUT of a room that has another (any) person present. Reuse the room-tier occupancy predicate (`_room_occupied` / `OccupancySubstrate` from v4.7.24).

### L3 (HIGH livability) — Volume continuity across platform boundary
Cross-platform generic transfer sets target volume to source volume. But WiiM/Sonos absolute volumes are not comparable — a Sonos at 0.4 is louder than a WiiM amp at 0.4 driving passive speakers. Add a per-room "volume calibration factor" (Number entity per room), applied on cross-platform transfers. REUSED opportunity: room config already has `room_media_player`; add a sibling `room_media_volume_scale` (default 1.0).

### L4 (MEDIUM livability) — Handoff latency
`TRANSFER_VERIFY_DELAY_SECONDS = 2` + `TRANSFER_DELAY_MS = 500` (unused per-grep) + BLE distance recheck. Total perceived silence gap during transfer is 2-4 seconds. For same-platform join, this is unnecessary — the join is instant. Gate the verify delay to generic/cross-platform transfers only.

### L5 (MEDIUM livability) — TTS / announcement collision
No coordination with HA TTS. If MF is mid-transfer (source at 10%, target starting) and an announcement fires on either speaker, the announcement plays at 10% (source) or over the just-transferred music (target). Subscribe to `SIGNAL_TTS_STARTING` (if it exists; else create one) → pause MF for the announcement window.

### L6 (MEDIUM livability) — Do-Not-Disturb / manual override
No user-facing "don't follow me right now" switch. Add per-person MF-enable Switch entity (already implied by `enable_for_person`/`disable_for_person` API but no UI). Simple deliverable.

### L7 (LOW livability) — Multi-person conflict resolution
If two enabled persons transition simultaneously into different rooms, the concurrency lock serializes. Whichever wins the race gets their music transferred; the other's transition is silently dropped (recorded as `cooldown_blocked` misleadingly). Add per-person queues or explicit conflict logging.

### L8 (LOW livability) — Frontend visibility of skip reasons
Skip reasons (`low_confidence`, `active_playback_blocked`, `cooldown_blocked`) live only in daily counters. Expose `last_skip_reason` + `last_skip_room_pair` as sensor attributes so users can see WHY their music didn't follow.

### L9 (LOW livability) — Ping-pong window is one-size-fits-all
`PING_PONG_WINDOW_SECONDS = 60` — reasonable for the 30-second bathroom trip but wrong for kitchen-to-dining (regular back-and-forth during a meal). Per-room-pair overrides via zone config.

---

## PART 3 — High-level plan (deliverables, prioritized)

### Tier classification
Per CLAUDE.md standing policy: cross-coordinator ripple (MF ↔ presence ↔ HVAC-sleep ↔ house-state) makes this regression-prone. **Elevate to Tier 2-DB (3 framing-disjoint reviews) for any deliverable touching the transfer decision path (D2, D3, D4, D6).** Pure additive/observability deliverables (D0, D5, D8, D11) can be Tier 1 hotfix cadence.

### D0 — Design doc + institutional record (Tier 1)
**Description:** Author `docs/Coordinator/MUSIC_FOLLOWING.md` capturing: architecture (event-driven, priority 30, wraps standalone class), all gates in order, cross-signal handlers (arrival stub called out), tuning knob catalogue with defaults, ping-pong location (`transitions.py` NOT MF), stat glossary (which counters are wired vs vestigial).

**Acceptance Criteria**
- **Verify:** Doc committed at `docs/Coordinator/MUSIC_FOLLOWING.md`.
- **Verify:** Doc references file:line for every gate and every CONF_*.
- **Test:** Manual read-through by planner in next cycle.

### D1 — Silent-actuator visibility (Tier 1 hotfix) — addresses C1
**Description:** Pre-flight availability guard on target media_player; new stat `target_unavailable`; extend the existing per-room "unavailable entities" sensor (v5.7.2 pattern) to include configured `room_media_player`; record last-skip reason on the diagnostic sensor.

**Acceptance Criteria**
- **Verify:** Attempted transfer into an `unavailable` target records `target_unavailable`, source is NOT faded, source volume is NOT touched.
- **Sensor:** `sensor.ura_music_following_coordinator_music_following` `last_skip_reason` attribute reads `target_unavailable`.
- **Sensor:** existing `sensor.<room>_unavailable_entities` includes `room_media_player` when configured and unavailable.
- **Test:** New test `test_target_unavailable_short_circuits` in `quality/tests/test_music_following.py`.
- **Live:** With master bedroom Sonos powered off, walk from kitchen to bedroom while music plays in kitchen — verify kitchen music continues playing, coordinator sensor `last_skip_reason=target_unavailable`, no service call errors in log.

### D2 — Sleep + Night gating (Tier 2-DB) — addresses L1
**Description:** Read `SIGNAL_HOUSE_STATE_CHANGED`; suppress transfers during `SLEEP`; conditional suppression during `HOME_NIGHT` (allow only same-dwell-room targets). New CONF `CONF_MF_SLEEP_SUPPRESS` (default True) and `CONF_MF_NIGHT_SUPPRESS_MODE` (options: off/dwell_only/on, default dwell_only).

**Acceptance Criteria**
- **Verify:** During `HouseState.SLEEP`, any incoming transition to `_on_person_transition` records `sleep_suppressed` and returns without touching media_players.
- **Verify:** During `HOME_NIGHT` with mode=dwell_only, transfer allowed to person's assigned dwell room only.
- **Test:** Tier 2-DB three framing-disjoint reviews (A: correctness of gate ordering; B: signal-subscription lifecycle + reload symmetry; C: no-flap on state transition edges).
- **Live:** Overnight run — verify no MF transfers logged between sleep_start and sleep_end.

### D3 — Guest-aware source-room guard (Tier 2-DB) — addresses L2
**Description:** Before transferring OUT of source room, check room-tier occupancy (via v4.7.24 `OccupancySubstrate` / `_room_occupied`). If source room shows any other occupant (identified or unidentified), suppress the transfer with new stat `source_has_others`.

**Acceptance Criteria**
- **Verify:** With person A in living-room playing music AND person B also in living-room, when A transitions to kitchen, music stays in living-room.
- **Test:** Occupancy predicate mock returns `occupied=True` after A leaves → transfer suppressed.
- **Live:** Two-person walk-through, log inspection.

### D4 — Fix ping-pong counter + same-room stat (Tier 1) — addresses C2
**Description:** Either wire `transitions.py:231` ping-pong suppression to increment MF's `ping_pong_suppressed` counter, or remove the counter to avoid #53. Prefer wiring — data value to see how often ping-pong fires per-person.

**Acceptance Criteria**
- **Sensor:** `ping_pong_suppressed` counter increments on A→B→A within 60s window.
- **Verify:** Same-room transitions recorded as `same_room` (new stat).

### D5 — Per-person MF Switch entities (Tier 1) — addresses L6
**Description:** New Switch platform entities `switch.music_following_<person>` binding to `enable_for_person`/`disable_for_person`. RestoreEntity for persistence.

**Acceptance Criteria**
- **Sensor:** Switch entity registered per tracked person.
- **Verify:** Toggle persists across restart (Bug Class #52 guard: don't coerce unavailable→OFF).
- **Test:** `test_mf_person_switch_restore`.

### D6 — Concurrency + staleness (Tier 2-DB) — addresses C3, C4, C5
**Description:** Rework `_on_person_transition` to (a) reject transitions older than N seconds inside the lock (`stale_transition` stat), (b) drop the `.locked()` short-circuit in favor of `try_acquire`, (c) add `MusicFollowing.async_teardown()` clearing all in-flight state, (d) add options-flow update listener that re-syncs `_enabled_persons`.

**Acceptance Criteria**
- **Verify:** Two rapid transitions serialize cleanly; second is recorded as `stale_transition` if age > threshold.
- **Verify:** After options-flow update removing person X from tracked_persons, X is no longer in `_enabled_persons`.
- **Test:** Tier 2-DB Framings — A: lock semantics + stat correctness; B: reload symmetry + teardown ordering; C: cross-coordinator (interaction with presence dispatch).

### D7 — Target picker platform-preference (Tier 1) — addresses C6
**Description:** In `_get_room_player` Strategy 3, sort candidates by (is-multiroom-platform DESC, alphabetical). Log WARNING on multi-player ambiguity.

**Acceptance Criteria**
- **Test:** Given `[bedroom_tv (generic), bedroom_sonos]`, picker returns `bedroom_sonos`.
- **Live:** Log inspection — WARNING logged once per ambiguous room per restart.

### D8 — Skip-reason attribute surface (Tier 1) — addresses L8
**Description:** Extend `get_diagnostic_data` to include `last_skip_reason`, `last_skip_from_room`, `last_skip_to_room`, `last_skip_time`. Wire from `_record_stat` when outcome is not `success`/`unverified`.

**Acceptance Criteria**
- **Sensor:** Attributes visible on MF diagnostic sensor.
- **Live:** After a real skip, attributes reflect it.

### D9 — Arrival-start decision (Tier 2 review) — addresses C7
**Description:** Either (a) implement `_handle_person_arriving` with a per-person preferred-media config (Sonos favorite / MASS radio URL) OR (b) remove the CONF and log at DEBUG only. **Recommend (b) for this cycle** — the "preferred media" surface is a separate feature that deserves its own cycle. Mark the CONF as deprecated in translations.

**Acceptance Criteria**
- **Verify:** Options-flow no longer shows `music_on_arrival_start`.
- **Verify:** Handler logs at DEBUG only.

### D10 — TTS coordination (Tier 2) — addresses L5
**Description:** Subscribe to a to-be-defined `SIGNAL_TTS_STARTING` / `SIGNAL_TTS_ENDED`. Suspend MF transfers during TTS window per-player.

**Acceptance Criteria**
- **Verify:** During active TTS on target, incoming transition is deferred (queued) up to N seconds, then executed.
- **Test:** Mock TTS signal fires → transfer waits → completes.

### D11 — Per-room volume calibration (Tier 1) — addresses L3
**Description:** New per-room CONF `room_media_volume_scale` (float 0.5-1.5, default 1.0) applied on cross-platform generic transfer.

**Acceptance Criteria**
- **Verify:** Kitchen→Bedroom transfer with `bedroom.room_media_volume_scale=0.7` sets target volume to `saved_source_volume * 0.7`.
- **Test:** Unit test with mock service capture.

### D12 — Verify-delay conditional (Tier 1) — addresses L4
**Description:** Skip `TRANSFER_VERIFY_DELAY_SECONDS` sleep when transfer method was same-platform `join`.

**Acceptance Criteria**
- **Verify:** Join-path transfer latency measured < 500ms (vs current ~2.5s).
- **Test:** Verify function called with `skip_wait=True` on join success.

### Sequencing
1. **D0** (design doc) — prerequisite institutional context.
2. **D1** (silent-actuator visibility) — highest correctness value, small blast radius, ships as a hotfix.
3. **D4 + D8** (stat cleanup + skip-reason surface) — small, unlocks live observability for the rest.
4. **D2** (sleep gating) — highest livability value, Tier 2-DB.
5. **D3** (guest guard) — Tier 2-DB; depends on OccupancySubstrate wiring pattern.
6. **D5, D7, D11, D12** — Tier 1 batch.
7. **D6** — Tier 2-DB reload-symmetry rework.
8. **D9** — deprecation cleanup.
9. **D10** — depends on TTS signal that doesn't exist yet; defer to a dedicated cycle.

### Falsifiable invariant (for Tier 2-DB reviews)
For any deliverable touching the transfer decision path, the invariant is:

> **Under any HouseState, any person set, any target availability state — MF SHALL NOT modify source volume, call `unjoin`, or call `play_media`/`join`/`transfer_queue` if the resulting user experience is "music disappears from source without appearing at target."**

Reviewer D (adversarial completeness) must falsify by finding a legal-config reachable path where source is faded/paused but target does not start playing.

---

## Appendix A — Existing MF constant surface (verified)

```
# const.py
CONF_MUSIC_FOLLOWING_ENABLED (L84)
CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED (L1042)
CONF_MUSIC_ANOMALY_SENSITIVITY (L1130)
MUSIC_TRANSFER_COOLDOWN_SECONDS = 8 (L1152)
CONF_MF_{COOLDOWN_SECONDS,PING_PONG_WINDOW,VERIFY_DELAY,UNJOIN_DELAY,
         POSITION_OFFSET,MIN_CONFIDENCE,HIGH_CONFIDENCE_DISTANCE} (L1167-1173)
DEFAULT_MF_* (L1175-1181)
CONF_MUSIC_ON_{HAZARD_STOP,ARRIVAL_START,SECURITY_STOP} (L1524-1526)
```

All proposed NEW additions above (`CONF_MF_SLEEP_SUPPRESS`, `CONF_MF_NIGHT_SUPPRESS_MODE`, `room_media_volume_scale`) are marked NEW because grep of the CONF_MF / CONF_MUSIC surface returned no equivalent.

## Appendix B — Files affected by prospective deliverables

- `custom_components/universal_room_automation/music_following.py` — D1, D3, D4, D6, D7, D11, D12
- `custom_components/universal_room_automation/domain_coordinators/music_following.py` — D1, D2, D5, D6, D8, D9, D10
- `custom_components/universal_room_automation/const.py` — D2, D9 (deprecation marker), D11
- `custom_components/universal_room_automation/config_flow.py` + `options_flow.py` — D2, D9, D11
- `custom_components/universal_room_automation/switch.py` — D5
- `custom_components/universal_room_automation/sensor.py` — D1, D4, D8
- `custom_components/universal_room_automation/transitions.py` — D4 (ping-pong hook)
- `custom_components/universal_room_automation/__init__.py` — D6 (options-flow update listener wiring)
- `quality/tests/test_music_following.py`, `test_music_following_coordinator.py` — every deliverable
- `docs/Coordinator/MUSIC_FOLLOWING.md` — D0 (new file)
- `docs/QUALITY_CONTEXT.md` — potential new bug class: "Vestigial counter (#53 subclass): MF `ping_pong_suppressed` never incremented because suppression happens upstream."
