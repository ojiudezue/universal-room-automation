# PLANNING — House-state restart restore + override dispatch (Tier 2-DB)

**Cards:** HOUSE-STATE-SLEEP-LOST-ON-RESTART-1, HOUSE-STATE-OVERRIDE-NOT-DISPATCHED-1
**Thread:** presence (shared primitive `HouseStateMachine` consumed by HVAC / security /
music-following / routine-forecaster / per-room automation chains / diag sensors / direct
readers).
**Tier:** 2-DB (operator-elevated, cross-coordinator ripple presence -> every consumer).
**Deploy:** HELD until operator go (operator 2026-09-29).
**Author:** ura-planner. **Date:** 2026-09-29.

## REV 2 changelog (2026-09-29)

Plan review: `docs/reviews/code-review/plan_review_house_state_restart_and_override.md`
(REVISE). Every finding addressed in this REV.

- F1 (HIGH): consumer census extended to direct readers (11 new file:line entries) and to
  override writers. Arrester-sunset side-effect of D2 called out and flagged for operator.
- F2 (HIGH): heartbeat save added. `saved_at` now tracks liveness (down time), not last
  transition. New rung-1 knob `HOUSE_STATE_HEARTBEAT_S`.
- F3 (HIGH): restore re-arms dwell (`state_since = now`); design says exactly how boot-settle,
  the machine, and dispatch interact so HVAC (seeded from the machine at `hvac.py:1425`) and
  the machine can never diverge. Integration test rewritten to match.
- F4 (HIGH): the 03:07 trace (in D0 RESULTS) proves the house-state signal DID drive the flip
  (`S1_reason_ladder reason=house_state_transition`). Zone sleep restore stays a non-goal.
- F5, F6 (HIGH / MED): D2 hook is routed through a single presence-owned dispatch helper that
  applies boot-settle + observation-mode gates AND writes the D7 row + activity-log row. Three
  idempotence edge cases named and each gets a test.
- F7 (MED): override-survives-restart is declared explicitly (recommended ON, flagged for
  operator).
- F8 (MED): D0 rewritten — Q1 drops `sensor.uptime`, uses recorder `homeassistant_start`
  events; Q2 written as done from `ura_activity_log`; heartbeat obviates the staleness prior.
- F9 (MED): live criterion moved to a daytime `sleep` override (no night restart).
- F10 (LOW): heartbeat knob rung named; Store key + version get const names.
- F11 (build prediction): manager.py load point pinned; tests use real `Store` I/O.

## Falsifiable invariant

> (A) Across an HA restart, no consumer of `SIGNAL_HOUSE_STATE_CHANGED` shall observe a
> house-state transition unless the *inferred* state, after boot-settle + normal dwell, genuinely
> differs from the state that was persisted immediately before shutdown (subject to
> `HOUSE_STATE_RESTORE_MAX_STALE_S`).
> (B) Every operator-driven override (set OR clear) that changes the *effective* state shall
> dispatch exactly one `SIGNAL_HOUSE_STATE_CHANGED` payload whose consumer effects are
> byte-identical to those of an equivalent inferred transition, and shall be subject to the same
> boot-settle + observation-mode gates.
> (C) The `HouseStateMachine.state` property and each *trust* consumer's cached view of house
> state can never diverge across a boot: either they both reflect the restored state, or the
> machine dispatches a real transition and every consumer updates on the signal.

## Institutional context verified

### Prior-art scan (code + plans + memory)

**Code — House-state machine and dispatch:**
- `domain_coordinators/house_state.py:108` `HouseStateMachine.__init__` — starts at
  `HouseState.AWAY`, no restore; `:213` `set_override` and `:223` `clear_override` mutate
  `_override` in place with NO signal dispatch (the D2 bug). `:200-202` — `transition()` clears
  an override silently (must NOT double-dispatch: presence already dispatches with
  old=effective).
- `domain_coordinators/manager.py:187` `_house_state_machine = HouseStateMachine()`;
  `:267` `house_state_machine` property; `:272` `house_state` property; `:408`
  `async_start` — the coordinator setup loop is at `:417`, and D1 load MUST run BEFORE that loop
  (see §D1). `homeassistant_stop` save hook registered here as well.
- `domain_coordinators/presence.py:6789` — the **only** current dispatcher of
  `SIGNAL_HOUSE_STATE_CHANGED`. Payload shape `{old_state, new_state, trigger, confidence}`
  (`:6792-6797`). Boot-settle gate at `:6768`, observation-mode gate at `:6780`.
- `domain_coordinators/presence.py:7602` `set_house_state_override` — routes to
  `manager.house_state_machine.set_override` / `clear_override` at `:7613` / `:7621`.

**Consumer census — SIGNAL_HOUSE_STATE_CHANGED subscribers (trust vs display):**
| # | File:line | Callback | Trust | Actions on transition |
|---|---|---|---|---|
| 1 | `hvac.py:1308`->`:4174` | `_handle_house_state_changed` | **trust** | Updates `_house_state`, preset resolution + zone update; sleep->bedroom sleep presets, away->HVAC away. |
| 2 | `security.py:749`->`:1076/:1123` | `_on_house_state_changed_signal` -> `_handle_house_state_intent` | **trust** | Arm/disarm intents keyed on away / home_* / sleep. |
| 3 | `music_following.py:302`->`:586` | `_handle_house_state_changed` | trust | SLEEP suppresses follow. |
| 4 | `routine_forecaster.py:189`->`:391` | `_handle_house_state_change` | display+learning | Incremental routine update. |
| 5 | `coordinator.py:1590`->`:856` | `_on_house_state_changed` | **trust** | Per-room `house_state_<state>` automation chains + AI rules (AI-toggle gated). |
| 6 | `__init__.py:2857/:2873` | `_bayesian_guest_listener` | trust | Guest inference sample. |
| 7 | `sensor.py:6446` `PresenceNextStateSensor` | display | Refresh. |
| 8 | `sensor.py:10177` | display | Refresh. |
| 9 | `hvac_override.py:903` `sunset_immune_holds` | **trust** — indirect | Runs on every house-state signal. **D2 side-effect**: `override_set`/`override_clear` now sunset arrester immune holds. Recommended: keep (matches inferred-transition semantics); **operator flag** because this is new behaviour for a manual override. |

**Direct readers of `manager.house_state` (D1 changes what each sees at boot):**
| File:line | Reader | Effect of restore |
|---|---|---|
| `hvac.py:1425` | HVAC boot seed of `_house_state` | **This is D1's mechanism for HVAC**; seed reads restored value instead of `away`. |
| `manager.py:623` `get_status` | Diag | Restored value in status snapshot. |
| `manager.py:808` snapshot | Diag | Same. |
| `energy.py:7378` | Energy read | Restored value. |
| `notification_manager.py:3766` | NM tag | Restored value. |
| `binary_sensor.py:2204/2243/2339` | away/sleep/guest binary sensors | Restored value at first update. |
| `presence.py:1850` | Presence self-read | Restored value. |
| `music_following.py:157-173` | MF seed | Restored value at seed. |
| `optimization.py:2169` | Optimizer read | Restored value. |
| `__init__.py:4311` | Setup read | Restored value. |
| `sensor.py:5371/5465/6480` | Diag sensors | Restored value. |

**Override writers (all route through the machine hook, so one hook covers all):**
- `presence.py:7613`, `:7621` (service + select fallback).
- `__init__.py:5690, :5695, :5698, :5709, :5711` (service handlers).
- `select.py:270, :275, :278` (select entity fallback path).
The plan's D2 test suite MUST include at least one fallback path (a `select.py` call
exercised directly) so all writers are proven to reach dispatch.

**Persistence prior art (REUSE):**
- `hvac.py:32` `from homeassistant.helpers.storage import Store`; `hvac.py:844`
  `Store(hass, 1, f"{DOMAIN}.hvac_zone_state")` — canonical URA persistence pattern.
- `memory_writers.write_house_state_transition` (`memory_writers.py:565`) — canonical D7 DB
  writer, already boot-suppresses `trigger="boot"` (`:576-604`).

**Plans / audits consulted:**
- `docs/planning/AUDIT_db_write_worker_slow_2026_09_29.md` — ~140 s per-boot loop freeze;
  explains why 19:17 awake restart's walk did not fire consumer actions (still in setup) while
  the 03:01 sleeping restart's walk DID (see D0 RESULTS trace).
- Memory `feedback_no_restart_during_sleep` — reason the live check is a daytime override,
  not a night restart.
- Memory `feedback_suppression_needs_discharge` — heartbeat is the liveness discharge.
- Memory `feedback_config_first_before_code` — confirmed no existing knob covers this.

**Verdict per proposed piece:**
| Piece | REUSE / NEW | Cite |
|---|---|---|
| Persist last house-state across restart | **REUSE** `helpers.storage.Store` pattern | `hvac.py:32,844` |
| Restore-at-boot on the machine | NEW methods | `house_state.py:117` |
| Heartbeat save (liveness) | NEW (uses `async_track_time_interval`) | REUSE HA helper |
| Staleness bound | NEW rung-1 const | `house_state.py` |
| Heartbeat interval | NEW rung-1 const | `house_state.py` |
| Store key + version consts | NEW named consts | `house_state.py` |
| Dispatch on override set/clear | REUSE payload shape + gates | `presence.py:6789, :6768, :6780` |
| Presence-owned dispatch helper (shared) | NEW small helper on presence | `presence.py:6789` |
| D0 measurement source | REUSE `ura_activity_log.house_state_change` + recorder | — |

## D0 — Measurement (done, orchestrator 2026-09-29)

**Q1 (recorder, `homeassistant_start` events over the last 10 days):**
```bash
ssh ha "sqlite3 /config/home-assistant_v2.db <<'SQL'
.headers on
.mode column
SELECT datetime(e.time_fired_ts,'unixepoch','localtime') AS start_ts
FROM events e JOIN event_types t USING(event_type_id)
WHERE t.event_type='homeassistant_start'
  AND e.time_fired_ts > strftime('%s','now','-10 days')
ORDER BY e.time_fired_ts;
SQL"
```
Rationale (F8): `sensor.uptime` is unreliable and did not match the walk seen in URA.
`homeassistant_start` fires after core is up (5-9 min after shutdown here, because of the
~140 s per-boot event-loop freeze — AUDIT_db_write_worker_slow_2026_09_29.md), so the URA
boot walk lands BEFORE the start event; the URA activity log carries the walk itself.

**Q2 (URA DB, `ura_activity_log` — house-state walk + consumer-visible writes in a +15 min
window around each start):**
```bash
ssh ha "sqlite3 /config/universal_room_automation/data/universal_room_automation.db <<'SQL'
.headers on
.mode column
SELECT datetime(created_ts,'unixepoch','localtime') AS t, coordinator, action, description
FROM ura_activity_log
WHERE created_ts > strftime('%s','now','-10 days')
  AND (action IN ('house_state_change','preset_change','climate_write')
       OR description LIKE '%house_state_transition%')
ORDER BY created_ts;
SQL"
```

### D0 RESULTS (2026-09-29, read-only)

- 20 restarts in 10 days. `homeassistant_start` fires 5-9 min after shutdown; the boot walk
  lands before start events (per Q2), so the walk is what consumers see first.
- **Every restart walks through the boot placeholder.** Last house_state_change before nearly
  every start event is `arriving -> <state> (trigger=deferred_retry)` — the boot walk itself.
  Examples: 09-29 19:17 `away->arriving->home_evening`; 09-29 03:01 `away->arriving->home_night`
  (Sleep lost; zones 1-2 Sleep->Home at 03:07); 09-27 22:21 `arriving->home_night`.
- **F4 answered by trace (09-29 03:01 incident):** at 03:07:41 CDT — the same second as
  `House state arriving -> home_night (trigger=deferred_retry)` — HVAC wrote zone_1 and zone_2
  `sleep -> home` via `S1_reason_ladder reason=house_state_transition (house=home_night)`. At
  03:09:42 `home_night -> sleep` and both zones went back to sleep. **The house-state walk drove
  the flip** (2 minutes of Home). Zone sleep persistence is NOT needed for this incident — it
  stays a non-goal.
- **Actioned consequences observed elsewhere:** 09-28 14:24-16:34 (5 restarts during the
  all-thermostat outage): house flapped home_day<->away<->arriving for 15-30 min after each
  boot with every-zone `-> away` preset writes (confounded by the outage; those writes are held
  by v5.103.24 item 2). Awake evening restarts (09-28 18:53, 19:22, 09-29 19:17): no actioned
  transition, because the walk completed during coordinator start-up under the ~140 s freeze.
- **Down-time distribution (proxy: shutdown -> `homeassistant_start`):** 5-10 min for all 20
  restarts observed. Well inside the proposed 1800 s default. Heartbeat (F2) makes this the
  authoritative age at run time.

## Deliverables

### D1 — Persist and restore last house-state across restart

**Named consts (all in `house_state.py`, rung-1 module constants):**
- `HOUSE_STATE_STORE_KEY: Final[str] = f"{DOMAIN}.house_state"`
- `HOUSE_STATE_STORE_VERSION: Final[int] = 1`
- `HOUSE_STATE_RESTORE_MAX_STALE_S: Final[int] = 1800` (30 min). Kill-switch: `0` disables
  restore (machine always starts AWAY; current behaviour).
- `HOUSE_STATE_HEARTBEAT_S: Final[int] = 60` (F2). Rationale: makes `saved_at` accurate to
  ~1 min. Rung 1 (behavioural, safety-adjacent; no operator entity). Kill-switch: `0`
  disables the heartbeat (falls back to change-only + stop saves).

**Design (F3, F2, F5 explicit):**

1. **Persisted record shape** (Store v1):
   `{state: str, state_since: iso8601, saved_at: iso8601, override: str|null,
     override_since: iso8601|null}`.
2. **Save triggers** (F2):
   - (a) On every accepted `transition()` / `force_state()` / `set_override()` /
     `clear_override()` via an in-machine `_on_change` hook (change save).
   - (b) On `hass` stop (single graceful flush).
   - (c) **Heartbeat**: `async_track_time_interval(HOUSE_STATE_HEARTBEAT_S)` — updates
     `saved_at` only (state/override unchanged unless they moved). This is the liveness
     discharge (memory `feedback_suppression_needs_discharge`).
   - The heartbeat is registered by the manager; unsubscribed on unload; disabled when the
     const is `0`.
3. **Load** (F11 — pinned location): in `CoordinatorManager.async_start` **BEFORE the
   `for coord_id, coordinator in self._coordinators.items()` loop at `manager.py:417`**.
   No coordinator has been set up yet, so no consumer has read `manager.house_state` and no
   listeners exist to dispatch to. Behaviour:
   - Read the record. If `now - saved_at <= HOUSE_STATE_RESTORE_MAX_STALE_S`:
     - `_state = restored.state`.
     - **`_state_since = now`** (F3: re-arm dwell; do NOT preserve the original because it
       would let the first inference bypass hysteresis). The trade-off: hysteresis
       min-dwell delays a real change by ~10 min for SLEEP after every restart — acceptable,
       and symmetric with today's behaviour where inference-only would take longer to reach
       SLEEP anyway.
     - Re-apply `_override` if present (F7 — see below).
   - Else (stale, missing, or corrupt): fall through to `AWAY` default; INFO log with
     `restore_age_s`, `staleness_max_s`, and reason.
   - Always log the actual `restore_age_s` at boot (D0 says this is what the builder should log).
4. **Presence interaction at boot (F3 — the anti-divergence rule):**
   - The machine is at the restored state before presence coordinator setup runs. HVAC seeds
     `_house_state` from `manager.house_state` at `hvac.py:1425` — that now matches the
     restored state (this is D1's actual HVAC mechanism, per F1).
   - Presence's first-tick inference runs INSIDE the boot-settle gate
     (`presence.py:6768`). Because inference may propose a transition (e.g. AWAY on
     cold-boot when census is empty), `transition()` today mutates the machine BEFORE the
     dispatch gate at `:6789`. **Rule**: while `self._boot_settle_done` is False, presence
     MUST NOT call `machine.transition()` at all — it may compute the proposal, log it, and
     defer. When boot-settle lifts, presence re-computes and calls `transition()` once; a
     real change dispatches through the signal path; a match to the restored state is a no-op.
   - This closes the divergence hole: HVAC's cached state and the machine's state are always
     kept in lock-step by the signal, and the machine is never silently mutated during
     boot-settle.
   - Trigger label on the first post-boot dispatch (if any): `"boot_restore_diverged"`.
     If inference matches restored: no dispatch, log `boot_restore_confirmed`.
   - Extend `memory_writers.write_house_state_transition` boot-suppression vocab to include
     `boot_restore_confirmed` (still emit for `boot_restore_diverged` — it is a real change).

**Override survives restart (F7 — explicit declaration):**
- **Recommended: YES** (override is persisted and re-applied if within staleness bound).
  Rationale: an operator who forces SLEEP right before a restart clearly intends it to
  persist; dropping it makes restart-as-remedy-for-anything more dangerous than it should be.
- Consumer visibility of the restored override is guaranteed by the anti-divergence rule
  above: the machine's `state` property returns the override; HVAC's boot seed reads that
  value; other trust consumers cache no house-state at boot (security / per-room chains read
  from signals only, so their view is empty until a real signal), but they will match the
  next inferred transition and any operator clear (which dispatches per D2).
- **Operator flag:** this is a behaviour change (override was ephemeral before). If the
  operator rejects it, set `override` to `null` on save. Default in code: persist.

**Files touched:** `house_state.py` (+methods, +consts, +change hook, +load/save),
`manager.py` (+`Store` construct, +load before `:417`, +stop-hook, +heartbeat interval),
`memory_writers.py` (extend boot-trigger vocab), `presence.py` (defer `transition()` during
boot-settle; add restored-state matcher; new trigger labels).

**Acceptance criteria (F3 rewritten so the criterion matches the design):**
- **Verify (unit):** save SLEEP with `state_since=t0`, `saved_at=t0`; construct fresh
  machine; load at `now=t0+60s` -> `state==SLEEP`, `_state_since==now` (F3), override
  round-trips. Load at `now=t0+STALE_MAX+1` -> `state==AWAY`, logs `restore_age_s` and
  reason.
- **Verify (unit):** heartbeat — with `HOUSE_STATE_HEARTBEAT_S=60`, machine unchanged for
  10 min; save file's `saved_at` advances every ~60 s; `state`, `state_since`, `override`
  unchanged.
- **Verify (integration):** restored SLEEP + census=0 at boot (would newly infer AWAY).
  During boot-settle, presence's proposed AWAY is DEFERRED (no `transition()` call, no
  mutation, no signal). After boot-settle lifts, presence re-computes; if still AWAY and
  dwell has elapsed, exactly ONE `SIGNAL_HOUSE_STATE_CHANGED` fires with
  `old="sleep", new="away", trigger="boot_restore_diverged"`. If inference converged back to
  SLEEP by then, zero signals fire and log records `boot_restore_confirmed`.
- **Verify (real Store I/O, F11):** load/save use `helpers.storage.Store` against a tmp
  path, not a hand-built dict.
- **Sensor:** `sensor.ura_house_state` reads `sleep` immediately post-restart when the D0
  record was `sleep` and fresh (no `arriving`/`home_*` walk visible on the sensor).
- **DB:** `ura_activity_log` shows zero `house_state_change` rows in the +15 min boot
  window when restore matched inference; one row with `trigger=boot_restore_diverged` when
  it did not.
- **Live (F9 — daytime, no night restart):** at daytime, force `sleep` via
  `ura.set_house_state`, wait 60 s for a heartbeat, restart HA. After boot: house state is
  `sleep`, HVAC bedroom presets are at sleep values, no zone flip to Home, no
  `house_state_change` row within the +15 min boot window. Clear override -> D2 exercises
  its own live path.

### D2 — Dispatch `SIGNAL_HOUSE_STATE_CHANGED` on override set/clear

**Design (F5, F6):**

1. Add a single presence-owned dispatch helper
   `presence._dispatch_house_state_change(old, new, trigger, confidence, source)` that:
   - Applies the boot-settle gate (same short-circuit as `presence.py:6768`).
   - Applies the observation-mode gate (same as `:6780`).
   - Calls `async_dispatcher_send(hass, SIGNAL_HOUSE_STATE_CHANGED, payload)` with the
     canonical payload shape (`:6792-6797`).
   - Writes the D7 row via `memory_writers.write_house_state_transition` and the
     `ura_activity_log.house_state_change` row (mirrors `presence.py:6744` and `:6800`).
   - Refactor: presence's existing dispatch site (`:6789`) is replaced by a call to this
     helper (behaviour-neutral — Review C: mutate the helper, both inference-driven and
     override-driven paths must fail together).
2. `HouseStateMachine` gains an `on_state_change: Callable | None` hook. The manager
   registers it with a thin adapter that resolves the presence coordinator and calls the
   helper. The machine itself does not import HA dispatch primitives.
3. **When the hook fires (F6 — the three edge cases):**
   - `set_override(X)`: fires iff `effective_state` **changed** (old effective != X).
     Trigger `override_set`.
   - `clear_override()`: fires iff there WAS an override AND the inferred state !=
     the-cleared-override (otherwise clearing is a no-op on effective state). Trigger
     `override_clear`.
   - `set_override(X)` when effective already == X: pin the override state (record intent)
     but do NOT dispatch (idempotent).
   - `transition()` at `:200-202` clears an override silently — the hook MUST NOT fire on
     this path, because presence's own dispatch already carries the correct old (effective)
     -> new payload. Implement via a `suppress_hook: bool = False` kwarg on
     `clear_override`, set True when called from within `transition()`.
4. **Confidence source (F6):** `1.0` for `override_set`; on `override_clear`, use the last
   confidence known to the inference engine
   (`presence._inference_engine.confidence`), read via the adapter — the machine has no
   access. If unavailable at call time (very early boot), pass `None`; the payload allows it.
5. **Loop-thread assertion (F11 build prediction e):** the helper asserts `hass.loop is
   asyncio.get_running_loop()` before dispatch. The service-call path is already on the
   loop; the assert protects future callers.

**Files touched:** `presence.py` (+helper, refactor `:6789`), `house_state.py` (+hook +
`suppress_hook` kwarg on `clear_override`), `manager.py` (+adapter wiring).

**Acceptance criteria:**
- **Verify (unit):** machine at inferred=HOME_EVENING, no override; call
  `set_override(SLEEP)` -> hook fires with `("home_evening","sleep","override_set")`. Call
  again -> no fire (idempotent). Call `clear_override()` -> hook fires with
  `("sleep","home_evening","override_clear")`. Now set inferred=SLEEP, then
  `set_override(SLEEP)` -> no fire (effective unchanged). Then `clear_override()` -> no
  fire (inferred == cleared value). Then `transition(HOME_NIGHT)` where an override was
  active -> presence's own dispatch fires exactly once, hook does not fire (F6:
  double-dispatch guard).
- **Verify (unit):** boot-settle gate — set the flag False, call `set_override(SLEEP)` ->
  no dispatch, machine still records the override. Lift the flag; next inference
  reconciles.
- **Verify (unit):** observation-mode gate — same shape.
- **Verify (integration, fallback path):** call
  `select.py:HouseStateSelect.async_select_option("sleep")` (the fallback path at
  `select.py:270-278`) — dispatch fires exactly once, HVAC receives the signal.
- **DB:** exactly one `ura_activity_log.house_state_change` row per fired dispatch, with
  `trigger` in `{override_set, override_clear}`; one `house_state_transition` DB row via
  the D7 writer.
- **Live (F9 — daytime):** with house at `home_evening`, call `ura.set_house_state` with
  `sleep`; within one second HVAC bedroom presets switch to sleep, security arms night,
  music-following gates to sleep behaviour. Arrester immune holds (`hvac_override.py:903`)
  sunset (declared side-effect; operator informed). Clear: everything reverts, one signal
  per event.

## Non-goals

- No change to inference logic (only boot-settle deferral of `transition()`).
- No new operator-visible entity (staleness + heartbeat are rung-1 consts this cycle).
- No change to `force_state` semantics (safety path).
- No change to guest / vacation transitions.
- **Zone sleep restore is out of scope** — the 03:01 incident trace (D0 RESULTS) proves the
  house-state signal drove the flip; zone sleep persistence is not required for this
  incident. If a future incident is traced to a zone-mode-only cause, card it separately.
- No change to the boot-settle window or observation-mode gating apart from adding the
  deferral of `transition()` inside boot-settle.

## Tier and review framings (3 disjoint, parallel)

- **Review A — correctness + edge cases + override-restore decision:** staleness math
  (monotonic vs wall clock, DST, missing `saved_at`); corrupt/partial Store payload;
  heartbeat drift; override + restore interaction (owns the F7 decision — including
  operator flag); the three F6 idempotence cases; `state_since=now` re-arm consequences;
  loop-thread assertion.
- **Review B — cross-coordinator ripple + lifecycle:** every consumer in the census (signal
  subscribers AND direct readers) behaves correctly on `override_set`/`override_clear` and
  on boot with a restored state (esp. HVAC boot seed at `hvac.py:1425`); arrester-sunset
  side-effect (`hvac_override.py:903`); ordering — load completes before the coordinator
  loop at `manager.py:417`; stop-hook and heartbeat unsub exactly once on unload; no
  dispatch during observation mode or boot-settle for either path.
- **Review C — persistence authority + test authority:** `Store` version + migration story;
  real-`Store` I/O in tests (tmp path), not dict; per-site mutation drill on the
  `_dispatch_house_state_change` helper (delete the `async_dispatcher_send` line — BOTH
  D1's post-boot-diverged test AND D2's integration test must fail with named
  assertions, not silently pass); at least one fallback-path (`select.py`) integration
  test; D0 SQL reproducible from this doc (Q1 + Q2 above).

Plan review before build: ONE adversarial pass per Tier 2-DB. Reviewer re-greps consumer
census (signal + direct) and re-runs Q1/Q2 independently.

## Sequence

1. D0 measurement — DONE (see D0 RESULTS).
2. Plan review — REV 1 returned REVISE; REV 2 addresses all findings; re-review before build.
3. Build D1 + D2 together (same primitive, one PR).
4. Suite + name-diff vs `pre-review-v<version>` baseline.
5. Three parallel Tier 2-DB reviews (A / B / C).
6. Fix-up round.
7. **STOP for operator go** (deploy held per operator 2026-09-29). Surface: (a) override
   survives restart Y/N, (b) arrester sunset on override Y/N.
8. Deploy, live validation (daytime override; Review D), README write-back into
   `README_v<version>.md`.
