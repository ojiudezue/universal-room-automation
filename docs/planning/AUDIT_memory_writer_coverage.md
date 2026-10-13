# AUDIT — Memory Writer Coverage (P2)

**Card:** part of `MEMORY-ROADMAP-1` follow-on (P2 — coverage audit)
**Scope:** read-only. No code changed.
**Companion:** `docs/planning/PLANNING_memory_roadmap_and_critique.md`

## 0. Headline finding — `memory_writers._schedule` silently drops writes

`memory_writers.py:82-93`:

```python
def _schedule(hass, coro) -> None:
    try:
        sched = getattr(hass, "async_create_background_task", None) or hass.async_create_task
        sched(coro)
    except Exception:
        try:
            coro.close()
        except Exception:
            pass
```

`hass.async_create_background_task` signature (verified in `.venv-ha`, `homeassistant.core.HomeAssistant.async_create_background_task`):
`(self, target: Coroutine, name: str, eager_start: bool = True)` — **`name` is required, no default.**
`_schedule` calls `sched(coro)` with only one positional arg. That call raises
`TypeError: missing 1 required positional argument: 'name'`, which the bare
`except Exception` swallows, then `coro.close()` discards the unrun
`log_memory_episode(...)` coroutine. **Every writer that routes its actual
DB write through `_schedule` never persists anything — not an error, a
silent no-op.** Confirmed against live data in §2: D4, D6, D7 are at 0 rows
while D5 (which bypasses `_schedule`) is live with 362 rows.

## 1. Inventory — every entry in `MEMORY_EPISODE_TYPES`

Registry: `const.py:5014-5044`. `MEMORY_FACT_TOPICS`: `const.py:5046-5064`.

| Episode type | Writer (file:line) | Call site(s) | Scheduling | Kill switch |
|---|---|---|---|---|
| `phantom_retro` (D4) | `memory_writers.py:101` `write_phantom_retro` | `coordinator.py:3574` (sync call) | **BROKEN** — ends in `_schedule` (`memory_writers.py:165`) | `PHANTOM_RETRO_ENABLED` |
| `away_transition_blocked` (D5) | `memory_writers.py:293` `AwayBlockEpisodeTracker._open` | `presence.py:6513-6519` (`hass.async_create_task(tracker.note_tick(...))`) | **OK** — outer call is `hass.async_create_task`; inside, `_open`/`_close_open` `await db.log_memory_episode(...)` directly, never touches `_schedule` | `AWAY_BLOCK_EPISODE_ENABLED` |
| `tracker_trust_excluded` (D6) | `memory_writers.py:517` `TrackerTrustExcludedWriter._emit` | `presence.py:6527` (writer instantiated), `.observe()` scheduled via `hass.async_create_task` at `presence.py:6534` | **BROKEN** — `observe()` is correctly scheduled, but inside it `await self._emit(...)` (`memory_writers.py:504`) and `_emit` ends in `_schedule` (`memory_writers.py:546`) | `TRACKER_TRUST_WRITER_ENABLED` |
| `house_state_transition` (D7) | `memory_writers.py:565` `write_house_state_transition` | `presence.py:7848` (sync call from `_dispatch_house_state_change`) | **BROKEN** — ends in `_schedule` (`memory_writers.py:633`) | `HOUSE_STATE_TRANSITION_WRITER_ENABLED` |
| `occupancy_phantom` | inline at `coordinator.py:4469` (D2 demotion) | same (inline, no separate function) | OK — `self.hass.async_create_task(_db.log_memory_episode(...))` directly | none named; implicit via D2 demotion path being live |
| `fan_transition_suppressed` | inline at `coordinator.py:3741` | same | OK — `self.hass.async_create_task(...)` directly | implicit via `FAN_TRANSITION_SUSPECT_WINDOW_S` gate |
| `comfort_fan_vetoed` | `fan_veto.py:564` | same | sync `_db.log_memory_episode(...)` call — needs confirmation it's awaited/scheduled by caller context (not traced further; low volume, 1 row/7d, treat as weakly-live) | n/a found |
| `actuation_conflict` | `hvac_fans.py:1983` | same | sync call in presumably-async context | n/a found |
| `exterior_track` | `exterior_track_linker.py:687` | same | `await db.log_memory_episode(...)` directly (async function) | n/a found — high volume by design |
| `sensor_dropout` | `sensor.py:1858-1860` `_check_dropout_episode` | `sensor.py:1795` `_handle_coordinator_update` | OK — `self.coordinator.hass.async_create_task(...)` directly, not `_schedule` | none named; gate is `prev==0 and cur>0` edge |
| `comfort_fan_on` | **no writer found** | — | — | — |
| `config_changed` | **no writer found** (only an unrelated `_on_config_changed` signal handler in `transit_validator.py:357`, not a memory writer) | — | — | — |
| `systemic_dropout` | **no writer found** | — | — | — |
| `hazard_recurrent` | **no writer found** | — | — | — |

## 2. Live counts (all-time + last 7 days)

```
ssh ha "sqlite3 .../universal_room_automation.db \
  "select episode_type,count(*),min(started_at),max(started_at) from memory_episodes group by 1""
```

| episode_type | all-time rows | last 7d rows | min | max | Status |
|---|---|---|---|---|---|
| `exterior_track` | 6957 | 872 | 2026-08-06 | 2026-10-11 | **LIVE** |
| `actuation_conflict` | 5074 | 371 | 2026-08-03 | 2026-10-12 | **LIVE** |
| `away_transition_blocked` | 362 | 72 | 2026-08-16 | 2026-10-12 | **LIVE** |
| `fan_transition_suppressed` | 231 | 24 | 2026-08-03 | 2026-10-11 | **LIVE** |
| `occupancy_phantom` | 189 | 18 | 2026-08-04 | 2026-10-12 | **LIVE** |
| `comfort_fan_vetoed` | 148 | 1 | 2026-08-02 | 2026-10-11 | **LIVE** (thin) |
| `phantom_retro` | 0 | 0 | — | — | **DEAD** — `_schedule` bug (§0); coroutine closed before write |
| `tracker_trust_excluded` | 0 | 0 | — | — | **DEAD** — `_schedule` bug (§0) |
| `house_state_transition` | 0 | 0 | — | — | **DEAD** — `_schedule` bug (§0) |
| `sensor_dropout` | 0 | 0 | — | — | **DEAD** — writer and scheduling are both correct; the `prev==0→cur>0` edge appears never to have fired in 2+ months. Not explained by the `_schedule` bug (this writer doesn't use it). Needs live re-check after the `_schedule` fix ships, since the three fixed writers may surface correlated sensor-dropout edges once house-state/tracker-trust episodes resume. |
| `comfort_fan_on` | 0 | 0 | — | — | **DEAD** — no writer exists; registered vocabulary slot only |
| `config_changed` | 0 | 0 | — | — | **DEAD** — no writer exists |
| `systemic_dropout` | 0 | 0 | — | — | **DEAD** — no writer exists |
| `hazard_recurrent` | 0 | 0 | — | — | **DEAD** — no writer exists |

**6 of 14 registered episode types have ever produced a row. 4 of those 6 are high/moderate volume and genuinely live. 3 types (`phantom_retro`, `tracker_trust_excluded`, `house_state_transition`) are dead specifically because of the `_schedule` bug — this is the single highest-value fix in this audit: one function fixes three writers at once.**

## 3. Facts tier (`memory_facts` by topic vs `MEMORY_FACT_TOPICS`)

```
ssh ha "sqlite3 .../universal_room_automation.db "select topic,count(*) from memory_facts group by 1""
```

| topic | rows | Status |
|---|---|---|
| `exterior_track_baseline` | 514 | live |
| `actuation_conflict_summary` | 236 | live |
| `phantom_recurrence` | 87 | live |
| `occupancy_reliability` | 1 | live (thin — one fact ever distilled) |
| `sensor_trust` | 1 | live (thin) |
| `occupancy_baseline` | 1 | live (thin) |
| `notification_hygiene` | 1 | live (thin) |
| `away_transition_blocked` | **0** | **FLAG** — matches PLANNING doc's P2: 362 episodes exist with no compaction rule distilling them into a fact yet |
| `adjacency_graph` | **0** | **FLAG** — matches PLANNING doc's P6 (adjacency-graph phase not built); reserved topic, no writer/rule exists |

## 4. Usefulness against recent investigations (2026-10-04 to 2026-10-11)

| Investigation | Memory held it? | Which episode type would answer it |
|---|---|---|
| Study A fan false occupancy + recheck undone by fan restore | **PART** — `occupancy_phantom` (D2 demotion, live) records the phantom adjudication, but the richer fan-release-correlated adjudication (`phantom_retro`, D4) that specifically models "recheck undone by fan restore" was **dead** (§0 bug) the whole investigation window | `phantom_retro` — dead, would need the `_schedule` fix |
| Bond fan entities flapping unavailable | **NOTHING** — `sensor_dropout` exists but has 0 rows; device-health is explicitly out of scope per operator (recorder covers it) | `sensor_dropout` (dead; not a `_schedule` casualty, separate gap) — but operator has ruled out building more device-health memory, so this is expected, not a gap to fix |
| Patio/garage Zigbee button automations not firing | **NOTHING** — no episode type in the registry models "automation did not fire"; this is an automation-trace/logbook question, not a memory-shape question | none registered; would require a new type outside this audit's scope |
| Master Toilet night light colour at sleep | **NOTHING** — light-color-at-transition is a config/room-behavior question, not an episodic adjudication; no type covers it and none should (not a phantom/trust/block/transition event) | none applicable |
| Census duplicate names | **NOTHING live** — `house_state_transition` snapshots carry `census_count`, `excluded_persons`, `unidentified_count` (exactly the fields this investigation needed) and `tracker_trust_excluded` tracks per-person exclusion churn, but **both were dead** (§0 bug) for the whole investigation window | `house_state_transition` + `tracker_trust_excluded` — both dead, both fixed by the same `_schedule` fix |
| Wigton HA stalls | **NOTHING** — no episode type models HA-core/event-loop stalls; this is infra/restart territory (HA recorder + journald), consistent with the operator's device-health-memory exclusion | none registered; out of scope by operator decision |

**Pattern:** the two investigations where memory *should* have helped and didn't (Study A fan phantom, census duplicate names) both trace to the same `_schedule` defect. Fixing `_schedule` would make `phantom_retro`, `tracker_trust_excluded`, and `house_state_transition` live, directly covering both gaps.

## 5. Recommendations

Operator decisions already in force: **no device-health memory build** (recorder covers it — rules out building out `sensor_dropout`/`systemic_dropout` further for that purpose). Table below respects that.

| Missing/broken writer | Value | Effort | Evidence trigger |
|---|---|---|---|
| **Fix `memory_writers._schedule`** (`memory_writers.py:82-93`) — pass `name` to `async_create_background_task`, or simplest: drop the `async_create_background_task` branch entirely and just call `hass.async_create_task(coro)` (mirrors every other inline writer in this file, which are all correctly live) | **High** — revives 3 of 14 registered types (`phantom_retro`, `tracker_trust_excluded`, `house_state_transition`) with zero new architecture; directly would have helped 2 of the 6 audited investigations | Trivial (1-3 line fix + a per-site mutation test proving the coroutine actually reaches the DB, not just that `_schedule` is called) | Already triggered — this audit is the trigger. Tier 1 hotfix. |
| Compaction rule for `away_transition_blocked` → fact topic `away_transition_blocked` (reserved, 0 rows) | Medium — 362 episodes with no distillation; this is exactly PLANNING doc P2's predicted shape (episodes accruing, facts thin) | Low — one compactor rule, hand-oracle fixture per existing discipline | Already crossed: >300 episodes with 0 facts is past any reasonable "worth a rule" threshold |
| `sensor_dropout` live-re-check after `_schedule` fix | Low-medium — may self-resolve once correlated writers are live again (house-state/tracker-trust transitions often coincide with sensor churn); if still 0 after a week post-fix, that is itself informative (edge condition truly never fires) | Zero — just re-run the §2 query | Re-check 7 days after the `_schedule` fix ships |
| `comfort_fan_on`, `config_changed`, `systemic_dropout`, `hazard_recurrent` — no writer exists | Unknown — never scoped/built; registered as reserved vocabulary only | n/a | Do not build speculatively; each needs its own problem statement before scoping (none raised in this audit's investigation sample) |

### Weekly zero-row trip-wire exemptions

A blanket "flag any episode type with 0 rows this week" trip-wire would permanently fire on legitimately-rare types. Exempt:

- `comfort_fan_vetoed` — thin by design (1 row/7d is normal; the condition it detects is rare)
- `away_transition_blocked`, `house_state_transition`, `tracker_trust_excluded` (once fixed) — edge-triggered episodic writers; weekly volume is naturally low (a handful to a few dozen) and a quiet week is not itself a regression signal
- `comfort_fan_on`, `config_changed`, `systemic_dropout`, `hazard_recurrent` — **not exempted, excluded entirely**: these have no writer, so a "0 rows" trip-wire on them would be permanently and uninformatively true. Exclude from any trip-wire until a writer is actually built.
- `sensor_dropout` — do not exempt; carry it in the trip-wire as a real zero-row candidate pending the re-check above.

Do **not** exempt `phantom_retro`: once `_schedule` is fixed it should produce occasional rows (it did in the hand-audit that motivated D4); a return to 0 post-fix is a real regression signal, not a quiet period.
