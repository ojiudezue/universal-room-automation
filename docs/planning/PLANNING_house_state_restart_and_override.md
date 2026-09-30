# PLANNING — House-state restart restore + override dispatch (Tier 2-DB)

**Cards:** HOUSE-STATE-SLEEP-LOST-ON-RESTART-1, HOUSE-STATE-OVERRIDE-NOT-DISPATCHED-1
**Thread:** presence (shared primitive `HouseStateMachine` consumed by HVAC / security /
music-following / routine-forecaster / per-room automation chains / diag sensors).
**Tier:** 2-DB (operator-elevated, cross-coordinator ripple presence -> every signal consumer).
**Deploy:** HELD until operator go (operator 2026-09-29).
**Author:** ura-planner. **Date:** 2026-09-29.

## Falsifiable invariant (state up front)

> Across an HA restart, no consumer of `SIGNAL_HOUSE_STATE_CHANGED` shall observe a house-state
> transition unless the *inferred* state, after its normal dwell/hysteresis, genuinely differs
> from the state that was persisted immediately before shutdown (subject to a bounded staleness
> knob). And: every operator-driven override (set OR clear) shall dispatch exactly one
> `SIGNAL_HOUSE_STATE_CHANGED` payload whose consumer effects are byte-identical to those of an
> equivalent inferred transition.

Two disjoint falsifiers: (a) after a nighttime restart within the staleness bound, HVAC
`_handle_house_state_changed` must NOT be called with `new_state="home_evening"` and old="away";
(b) a service-call override away->sleep must reach `hvac.py:_handle_house_state_changed`,
`security.py:_on_house_state_changed_signal`, and `coordinator.py:_on_house_state_changed`.

## Institutional context verified

### Prior-art scan (code + plans + memory)

**Code — House-state machine and dispatch:**
- `domain_coordinators/house_state.py:108` `HouseStateMachine.__init__` — starts at `HouseState.AWAY`,
  no restore; `:213` `set_override` and `:223` `clear_override` mutate `_override` in place with NO
  signal dispatch (the bug).
- `domain_coordinators/manager.py:187` `_house_state_machine = HouseStateMachine()` — constructed fresh
  each setup; single instance, exposed via `house_state_machine` property (`:267`).
- `domain_coordinators/presence.py:6789` — the **only** current dispatcher of
  `SIGNAL_HOUSE_STATE_CHANGED`, inside `_run_inference` after boot-settle + observation-mode gates.
  Payload shape: `{old_state, new_state, trigger, confidence}` (`:6792-6797`).
- `domain_coordinators/presence.py:7602` `set_house_state_override` — calls
  `manager.house_state_machine.clear_override()` or `set_override(...)`, but never dispatches.
- `domain_coordinators/presence.py:6744` writes D7 `house_state_transition` memory episode via
  `memory_writers.write_house_state_transition` and DB row.

**Code — Consumers of `SIGNAL_HOUSE_STATE_CHANGED` (producer/consumer census, full sweep):**
| # | File:line | Callback | Trust vs display | Actions on transition |
|---|---|---|---|---|
| 1 | `hvac.py:1308`->`:4174` | `_handle_house_state_changed` | **trust** | Sets `_house_state`, drives preset resolution + zone update; sleep -> bedroom sleep presets, away -> HVAC away presets. Boot seed at `:1425` from `manager.house_state`. |
| 2 | `security.py:749`->`:1076/:1123` | `_on_house_state_changed_signal` -> `_handle_house_state_intent` | **trust** | Arm/disarm intents keyed on away / home_* / sleep. |
| 3 | `music_following.py:302`->`:586` | `_handle_house_state_changed` | trust | Follow-mode gating; SLEEP suppresses follow. |
| 4 | `routine_forecaster.py:189`->`:391` | `_handle_house_state_change` | display+learning | Incremental routine update. |
| 5 | `coordinator.py:1590`->`:856` | `_on_house_state_changed` | **trust** | Per-room: fires `house_state_<state>` automation chains + AI rules (AI-toggle gated). |
| 6 | `__init__.py:2857/:2873` | `_bayesian_guest_listener` | trust | Guest inference sample. |
| 7 | `sensor.py:6446` `PresenceNextStateSensor` | display | Sensor refresh. |
| 8 | `sensor.py:10177` | display | Sensor refresh. |
| 9 | `switch.py:3415` (comment ref only) | n/a | — |

**Persistence prior art (REUSE candidates, not new):**
- `hvac.py:32` `from homeassistant.helpers.storage import Store` + `hvac.py:844`
  `Store(hass, 1, f"{DOMAIN}.hvac_zone_state")` — the canonical URA pattern for persisting
  coordinator state across restart (zone snapshot restored at boot). **REUSE this pattern** for a
  new `Store(hass, 1, f"{DOMAIN}.house_state")` inside `HouseStateMachine` (or its owner,
  CoordinatorManager). No new library. No RestoreEntity needed — `HouseStateMachine` is not an
  entity.
- `memory_writers.write_house_state_transition` (`memory_writers.py:565`) — every real transition
  already writes a DB row. **REUSE** as the D0 measurement source (see below), do not add a new writer.

**Plans consulted:**
- `docs/planning/AUDIT_db_write_worker_slow_2026_09_29.md` — the ~140 s per-boot loop freeze that
  explains why last night's 19:17 walk did not fire consumer actions (they were still in setup).
  That freeze is a coincidence guard, not a fix — the walk is real and will fire once boot latency
  drops.
- Memory `feedback_no_restart_during_sleep` — restart-during-sleep is the reproduction trigger.
- Kanban card `BOOT-EVENT-LOOP-FREEZE-1` (related, not blocking).

**Memory bodies pulled:** `feedback_suppression_needs_discharge` (any grace/deferral has a
discharge + backstop + restart clause — applies to the staleness bound), `feedback_config_first_before_code`
(the staleness bound and the override behaviour are both knobs — confirmed no existing setting
covers them).

**Design docs read:** none in `docs/Coordinator/` covers `house_state.py` directly; this plan
extends the machine's contract and its README section will be written back post-live.

**Verdict per proposed piece:**
| Piece | REUSE / NEW | Cite |
|---|---|---|
| Persist last house-state across restart | **REUSE** `helpers.storage.Store` pattern | `hvac.py:32,844` |
| Restore-at-boot into `HouseStateMachine` | NEW method on the machine | `house_state.py:117` (constructor) |
| Staleness bound knob | NEW named module constant on the ladder (rung 1: not operator-tunable — safety-adjacent) | `const.py` |
| Dispatch on override set/clear | **REUSE** existing dispatcher shape from `presence.py:6789` | `presence.py:6789-6797` |
| D0 measurement source | **REUSE** `house_state_transition` DB table (D7 writer) + recorder | `memory_writers.py:565` |

## D0 — Measurement first (I will run; read-only, one shot)

Run BEFORE build, results go in this doc. Two queries:

**Q1 (recorder, past 10 days of restarts and their house-state walk):**
```bash
ssh ha "sqlite3 /config/home-assistant_v2.db <<'SQL'
.headers on
.mode column
WITH restarts AS (
  SELECT s.last_updated_ts AS restart_ts
  FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id
  WHERE m.entity_id='sensor.uptime' AND s.last_updated_ts > strftime('%s','now','-10 days')
),
walk AS (
  SELECT s.last_updated_ts, s.state
  FROM states s JOIN states_meta m ON s.metadata_id=m.metadata_id
  WHERE m.entity_id='sensor.ura_house_state'
    AND s.last_updated_ts > strftime('%s','now','-10 days')
)
SELECT datetime(r.restart_ts,'unixepoch','localtime') AS restart,
       (SELECT w.state FROM walk w WHERE w.last_updated_ts < r.restart_ts
         ORDER BY w.last_updated_ts DESC LIMIT 1) AS state_before,
       (SELECT w.state||'@'||round(w.last_updated_ts-r.restart_ts,0)||'s'
          FROM walk w WHERE w.last_updated_ts >= r.restart_ts
          ORDER BY w.last_updated_ts LIMIT 6) AS first_states_after
FROM restarts r ORDER BY r.restart_ts;
SQL"
```

**Q2 (URA DB, house-state transitions + consumer-visible actuations within +10 min of each
restart):** join `house_state_transition` rows and `climate_write` / `activity_log`
`house_state_change` rows on time-window; count how many restarts produced actioned
transitions (HVAC preset writes, security intents, per-room chain fires). Exact SQL keyed on
the two tables' schemas (verify column names live at run time).

D0 exit criterion: a table `restart_ts | state_before | walked_through | actioned?` for every
restart in the window. This is the empirical prior for the staleness bound (`STALE_MAX_S`).

### D0 RESULTS (orchestrator, 2026-09-29, read-only; script scratchpad hs_d0.py: recorder `homeassistant_start` events x `ura_activity_log`)

- 20 restarts in 10 days. `homeassistant_start` fires 5-9 min after the shutdown (boot includes the ~140 s event-loop freeze, AUDIT_db_write_worker_slow_2026_09_29.md), so the boot walk lands BEFORE the start event.
- **Every restart walks through the boot placeholder**: the last house_state_change before nearly every start event is `arriving -> <state> (trigger=deferred_retry)` (the boot walk itself), e.g. 09-29 19:17 away->arriving->home_evening; 09-29 03:01 away->arriving->home_night (Sleep lost, zones 1-2 Sleep->Home at 03:07); 09-27 22:21 arriving->home_night.
- **Actioned consequences observed:** 09-29 03:01 (HVAC Sleep->Home, the incident). 09-28 14:24-16:34 (5 restarts during the all-thermostat outage): house flapped home_day<->away<->arriving for 15-30 min after each boot with every-zone `-> away` preset writes (confounded by the outage; the writes themselves are now held by v5.103.24 item 2). Awake evening restarts (09-28 18:53, 19:22, 09-29 19:17): no actioned transition, because the walk completes during coordinator start-up.
- Staleness prior: all 20 restarts had the pre-restart state < 15 min old at shutdown; the 1800 s default for HOUSE_STATE_RESTORE_MAX_STALE_S covers every observed restart with margin.

## Deliverables

### D1 — Persist and restore last house-state across restart (`HouseStateMachine` scope)

**Design:**
- Add `HouseStateMachine.async_load(store: Store)` and `async_save(store: Store)` methods.
- Persisted record shape: `{state: str, state_since: iso8601, saved_at: iso8601, override: str|null}`.
- On save: called (a) on every accepted `transition()` / `force_state()` / `set_override()` /
  `clear_override()` via a small `_on_change` hook and (b) on `hass` stop (single-writer through
  `Store.async_save`, no per-tick writes).
- On load (in `CoordinatorManager.async_start`, before `presence` coordinator starts firing):
  read the record; if `now - saved_at <= STALE_MAX_S` set `_state = restored.state`,
  `_state_since = restored.state_since` (preserves dwell so hysteresis behaves), and re-apply the
  persisted override if any. If stale (or missing / corrupt), fall through to `AWAY` default and
  log INFO with the reason.
- Presence `_run_inference` on its first post-boot tick: if the current inference equals the
  restored `state`, log `trigger="boot_restore_confirmed"` and DO NOT dispatch
  `SIGNAL_HOUSE_STATE_CHANGED` (this is already suppressed by the boot-settle gate at
  `presence.py:6768`; the change here is that after the gate lifts, the machine is already at the
  restored state so no walk happens). If the inference differs after normal dwell, that dispatch
  is a real transition and fires as today.
- Boot-suppression alignment: `memory_writers.write_house_state_transition` already suppresses
  `trigger="boot"` (`memory_writers.py:576-604`). Extend the recognised trigger vocabulary to
  include `"boot_restore_confirmed"` so the first tick after restore does not emit a mirror row
  for a non-transition.

**New constant (rung 1 — module constant, review-gated, safety-adjacent):**
- `HOUSE_STATE_RESTORE_MAX_STALE_S: Final[int] = 1800` in `house_state.py` (30 min). Rationale
  in one line: sleep hysteresis is 600 s and typical restart takes 5-10 min today; 30 min covers
  planned deploys without over-trusting a stale snapshot. Not exposed as a live entity — behavioural
  safety-adjacent number (Numbers-Get-Knobs rung 1). Kill-switch semantics documented on the
  constant: setting to 0 disables restore (machine always starts AWAY, current behaviour).

**Files touched:** `house_state.py` (+methods, +constant, +change hook), `manager.py`
(construct `Store`, call `async_load` before presence starts, register a `homeassistant_stop`
save hook), `memory_writers.py` (extend boot-trigger vocabulary), `presence.py`
(mark the first post-restore tick trigger).

**Acceptance criteria:**
- **Verify:** unit test — save state=SLEEP at t0, construct fresh machine, load with
  `now-saved_at=60s` -> `state == SLEEP`, `dwell_seconds ~= (now - state_since)`; with
  `now-saved_at=STALE_MAX+1` -> `state == AWAY`.
- **Verify:** integration test — with a saved SLEEP record inside the staleness bound and a
  presence inference that would newly infer AWAY, no `SIGNAL_HOUSE_STATE_CHANGED` fires until
  presence's normal dwell elapses; then it fires exactly once with `old="sleep"`.
- **Sensor:** `sensor.ura_house_state` reads `sleep` immediately after restart (no `away ->
  arriving -> home_*` walk) when D0 record was `sleep` and fresh.
- **DB:** the `house_state_transition` table gains no rows within the boot window when the
  restored state matches inference (assert via query 5 min after restart).
- **Live:** deploy-and-restart at night — HVAC does NOT switch bedroom zones from Sleep to Home;
  `hvac.py:_handle_house_state_changed` receives no away/arriving/home_* call in the boot window;
  `activity_log` shows zero `house_state_change` rows in the boot window.

### D2 — Dispatch `SIGNAL_HOUSE_STATE_CHANGED` on override set/clear

**Design:**
- `HouseStateMachine.set_override` / `clear_override` today mutate `_override` silently. Add a
  callable hook `on_state_change: Callable[[str, str, str], None] | None` stored on the machine;
  the manager registers a callback that dispatches `SIGNAL_HOUSE_STATE_CHANGED` with the exact
  payload shape used at `presence.py:6789` (`old_state`, `new_state`, `trigger`, `confidence`).
  Trigger values: `"override_set"` and `"override_clear"`. Confidence: `1.0` for set, echo the
  inference-engine confidence for clear.
- `presence.set_house_state_override` (`:7602`) keeps its current call to
  `manager.house_state_machine.set_override` — dispatch happens inside the machine's hook, so
  service call, select entity, and any future caller all route through the SAME dispatcher (no
  duplication risk).
- Idempotence: if `set_override(state)` is called and the current *effective* state
  (property `state`) already equals the target, do NOT dispatch (avoid a no-op flap).
  Same for `clear_override` when no override was active.

**Files touched:** `house_state.py`, `manager.py` (registration only).

**Acceptance criteria:**
- **Verify:** unit test — machine at inferred=HOME_EVENING, no override; call
  `set_override(SLEEP)` -> hook fires with `("home_evening", "sleep", "override_set")`. Second
  identical call -> no fire. `clear_override()` -> hook fires with `("sleep", "home_evening",
  "override_clear")`.
- **Verify:** integration test — call `presence.set_house_state_override("sleep")`; observe
  `hvac.py:_handle_house_state_changed` invoked with `new_state="sleep"` and HVAC preset
  resolution runs (zone updates called).
- **Sensor:** `sensor.ura_house_state` flips to `sleep` on override; back to inferred on clear.
- **DB:** one `house_state_transition` row per set/clear with the `override_*` trigger.
- **Live:** with house at `home_evening`, call `ura.set_house_state` with `sleep`; within one
  second HVAC bedroom presets switch to sleep, security arms night, music-following gates
  to sleep behaviour. Clear: everything reverts.

## Non-goals

- No change to inference logic in `presence._run_inference` (only the trigger label on the first
  post-restore tick).
- No new operator-visible entity (staleness is a module constant this cycle; can graduate to a
  Number if D0 or live data shows the operator wants to tune it).
- No change to `force_state` semantics (safety path).
- No changes to guest / vacation state transitions.
- No change to the boot-settle window or observation-mode gating.

## Tier and review framings (3 disjoint, all parallel)

- **Review A — correctness + edge cases:** staleness math (monotonic vs wall clock; DST; missing
  `saved_at`); corrupt / partial Store payload; override + restore interaction (restored override
  must fire a set-dispatch or NOT? decision: NO fire on load, because no consumer state can have
  changed while we were off — the load establishes ground truth, and any real drift will fire
  through inference within one dwell); idempotence of set/clear override; `state_since`
  preservation vs replay attacks (clamp `dwell` to `>=0`).
- **Review B — cross-coordinator ripple + lifecycle:** confirm ALL 6 trust consumers behave
  correctly on `override_set`/`override_clear` and on suppressed-boot cases; ordering — load
  MUST complete before presence coordinator start dispatches; save hook on `homeassistant_stop`
  registered exactly once and cleaned up on unload; no dispatch during observation mode (route
  override dispatch through the same observation-mode gate presence uses at `presence.py:6780`).
- **Review C — persistence authority + test authority:** `Store` version + migration story; the
  restore test must drive real `Store` I/O (tmp path), not a hand-built dict; a per-site mutation
  drill on the dispatch hook proves it is load-bearing (delete the dispatch line -> D2 integration
  test must fail with a named assertion, not silently pass); D0 SQL is reproducible from this doc.

Plan review before build: ONE adversarial plan review per Tier 2-DB rule; reviewer re-greps the
consumer census and re-runs the D0 queries independently.

## Sequence

1. D0 measurement (I run; results appended to this doc).
2. Plan review (one pass, framing = adversarial completeness on consumer census).
3. Build D1 + D2 together (same machine, one PR).
4. Suite + name-diff vs `pre-review-v<version>` baseline.
5. Three parallel Tier 2-DB reviews (A / B / C).
6. Fix-up round.
7. **STOP for operator go** (deploy held per operator 2026-09-29).
8. Deploy, live validation (Review D), README write-back into `README_v<version>.md`.
