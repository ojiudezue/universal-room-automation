# PLANNING — Substrate Re-subscribe on Room Add / Remove / Edit

**Cycle:** post-v5.11.0 (develop)
**Author:** ura-planner
**Date filed:** 2026-07-10
**Tier:** **Tier 2-DB** (standing policy — shared primitive consumed by room/zone/house tiers; three framing-disjoint reviews)
**Scope:** Small, surgical wiring fix. NOT a substrate redesign.

**Framing.** This cycle **restores the pre-v4.7.24 per-room-onboarding
guarantee.** Before commit `e165e1cb` (v4.7.24 substrate unification,
2026-06-05), each ROOM coordinator registered its own
`async_track_state_change_event` over its Tier-1 sensors at ROOM-entry
setup time (`git show e165e1cb~1:custom_components/universal_room_automation/coordinator.py`
~L968-978: `"Room %s: Event-driven mode — %d Tier 1 sensors (immediate)"`).
Because ROOM `async_setup_entry` runs at entry-add time, a newly onboarded
room was event-driven immediately — no restart required. v4.7.24
**centralized subscription into the substrate built once at
PresenceCoordinator setup** and — as an unintentional side effect —
**lost the per-entry lifecycle hook.** The acceptance bar for this cycle
is exactly the pre-June-5 behavior: a room added without restart is
event-driven from ROOM setup.

**Why this stayed invisible for a month.** Every ROOM entry in the house
predates the substrate cycle. The regression can only manifest on a room
onboarded WITHOUT a subsequent HA restart, and the first such room was
"Master Bath Toilet" onboarded 2026-07-09 08:23 — 34 days after the
regression shipped.

---

## Falsifiable invariant

*After any ROOM `ConfigEntry` transitions to LOADED, UNLOADED, or has its
options updated, the `OccupancySubstrate` subscription set MUST equal the
union of CONF_MOTION_SENSORS ∪ CONF_MMWAVE_SENSORS ∪
CONF_OCCUPANCY_SENSORS across all currently-LOADED ROOM entries — with
no observable dispatch gap (no lost edges) and no double-dispatch during
swap (no duplicate edges) — WITHOUT requiring an HA restart.*

Reviewer C (adversarial completeness) falsifies exactly that.

---

## Root cause (verified 2026-07-10 live + code + git history)

- **Pre-regression (pre-`e165e1cb`).** Each ROOM coordinator registered
  its own state-change listener at ROOM `async_setup_entry` time
  (coordinator.py ~L968-978 pre-substrate). Per-entry lifecycle was free
  because every ROOM's setup path went through that code.
- **Post-regression (v4.7.24, `e165e1cb`, 2026-06-05).** Substrate is
  constructed and `async_setup()`-ed once in
  `PresenceCoordinator.async_setup` at `presence.py:2170-2192`.
  `OccupancySubstrate.async_setup` enumerates ROOM entries from
  `hass.config_entries.async_entries(DOMAIN)` and registers exactly ONE
  `async_track_state_change_event` over the entities discovered at that
  moment (`occupancy_substrate.py:143-296`, subscription registered at
  `:265-275`).
- **No re-invocation trigger exists.** ROOM `async_setup_entry`
  (`__init__.py:3472-3489`) constructs a `UniversalRoomCoordinator` and
  calls `async_config_entry_first_refresh()`, but does not notify the
  presence coordinator or the substrate. `_async_update_listener`
  (`__init__.py:4795-4847`) either suppresses (comfort sliders) or
  triggers a ROOM reload — no substrate refresh signal in either path.
- **Live evidence (2026-07-09).** "Master Bath Toilet" onboarded 08:23
  without restart. Median raw-motion → light latency ~11s (worst 34s,
  one blip dropped); pre-fix comparable rooms ~1.5s. The 34s upper bound
  = the room coordinator's poll interval. Substrate never subscribed.

## Institutional context verified

### Greps run + results

- `OccupancySubstrate` construction site — REUSED
  `presence.py:2170` (single constructor call).
- `async_setup` re-entry semantics — REUSED. `occupancy_substrate.py:151-153`
  documents "Safe to invoke multiple times — each call performs a clean
  re-discovery"; `_teardown_listeners` at `:303-313` clears
  `self._unsub_listeners`. This is the primitive we call from the new hook.
- **Pre-substrate per-entry hook — REUSED (as design intent).**
  `git show e165e1cb~1:custom_components/universal_room_automation/coordinator.py`
  ~L968-978 = the pre-regression pattern we're restoring at a NEW
  granularity (signal-driven substrate refresh, not per-room listener).
- `_unsub_substrate_listeners` (Bug Class #50 fix pool) — REUSED
  `coordinator.py:292, 915-917, 1040-1046`. Room-tier substrate
  subscription is kept in a dedicated list that survives
  `_update_signal_subscriptions` rebuilds. Our design MUST NOT regress
  this: we are not touching the room coordinator's substrate listener at
  all; we are refreshing the substrate's OWN entity subscription set.
- Room entry announcement / signal — **NEW SIGNAL** required.
  `__init__.py:3472-3489` (ROOM `async_setup_entry`) does not dispatch
  any signal indicating "room loaded". Grep of `signals.py` for
  `SIGNAL_ROOM_*` returns nothing. Zone manager does not currently
  rediscover on room add. NEW because no equivalent exists.
- `_async_update_listener` for ROOM entries — REUSED
  `__init__.py:4827-4847`. Comfort-slider writes are already
  reload-suppressed; other ROOM options writes fall through to full
  reload. A full reload today ALREADY forces substrate resubscribe via
  presence coordinator teardown+re-setup (verified). The gap is limited
  to **suppressed** ROOM options writes AND to add/remove without
  restart. A defensive hook for options-updated is cheap and guards
  against future `_ROOM_SUPPRESS_KEYS` expansion silently reopening the
  gap.
- HA event bus for entry lifecycle — REUSED. HA does not fire a
  first-class `entry_loaded` event. Standard pattern is to dispatch from
  the entry's own `async_setup_entry` and subscribe consumers via
  `async_dispatcher_connect`. Both patterns already used in this
  codebase (`__init__.py:3479`, various coordinators).

### Prior planning docs consulted

- `docs/planning/PLANNING_occupancy_substrate_unification.md` (skim) —
  the v4.7.24 design. Confirms substrate is intentionally centralized;
  per-entry lifecycle was **not** in scope, which is exactly the
  regression this cycle fixes.
- `docs/planning/PLANNING_reconcile_on_return.md` (skim) — D2.9 re-arm
  pattern (Bug Class #50 recurrence guardrail). Same failure class of
  concern: listener that must be re-installed on every rebuild.

### Memory bodies pulled

- `v4.7.24 substrate live` — B-C1 CRITICAL: substrate subscription
  clobbered by periodic `_update_signal_subscriptions` rebuild. Fix
  moved substrate sub to `_unsub_substrate_listeners` (a distinct pool).
  Our design must not create a symmetric hazard on the substrate's OWN
  subscription list.

### Design docs read

- No `docs/Coordinator/PRESENCE.md` currently — substrate section
  covered inline in the unification planning doc above.

### Code locations surveyed end-to-end during scoping

- `custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py` (full read)
- `custom_components/universal_room_automation/domain_coordinators/presence.py:2140-2260`, `:1390-1400`, `:2726` (handler), `:5879` (teardown)
- `custom_components/universal_room_automation/__init__.py:1010-1050` (integration setup), `:3450-3489` (ROOM async_setup_entry), `:4795-4847` (update listener), `:3804` (`_unsub_substrate_listeners` retrieval on unload)
- `custom_components/universal_room_automation/coordinator.py:985-1135` (substrate subscription registration + rebuild hook)
- Pre-regression comparison: `git show e165e1cb~1:custom_components/universal_room_automation/coordinator.py` ~L968-978

---

## Design — event-driven refresh, no periodic rescan

**Chosen mechanism.** A new signal
`SIGNAL_ROOM_ENTRY_LIFECYCLE(entry_id, room_name, action)` (action ∈
`{"loaded", "unloaded", "options_updated"}`) is dispatched from the ROOM
entry's own `async_setup_entry` (after the coordinator is stored, before
`return True`), from the ROOM unload path (before returning), and from
`_async_update_listener` when the write is options-suppressed. The
`PresenceCoordinator` subscribes to this signal and calls a new
`OccupancySubstrate.refresh_subscriptions()` coroutine, which:

1. Re-enumerates ROOM entries and rebuilds the desired `(entity_id,
   room_name, kind)` set.
2. Diffs against `self._entity_to_room_kind` — computes `added`,
   `removed`, `re-classified` sets.
3. **Atomic swap.** Creates the NEW `async_track_state_change_event`
   subscription over the FULL new entity list BEFORE calling any prior
   unsub. Once the new sub is registered, seeds any newly-added entities
   from `hass.states.get()` (v4.7.18.1 B-HIGH-1 pattern; already in
   `async_setup`), then unsubs the OLD listener. During the brief
   overlap window, `_handle_state_change` is idempotent per-kind:
   `prior == occupied` short-circuits (`:383-384`), so a duplicate edge
   cannot double-dispatch. For a REMOVED entity, an in-flight event
   whose `entity_id` is no longer in `_entity_to_room_kind` (repointed
   BEFORE the old unsub fires) hits the `mapping is None` short-circuit
   at `:365-367`. Both sides safe.
4. Prunes `_raw_state` rooms whose entries are gone.
5. If a room is added while `_boot_settle_done=True`, immediately
   dispatch True-slot synthetic edges for the newly-seeded entities of
   that room (mirrors `release_boot_settle`) — otherwise the new room
   stays "silent" until the next real edge.

**Ordering (presence not up yet when a room loads).** The ROOM
`async_setup_entry` dispatches the signal unconditionally. If the
presence coordinator has not yet installed its subscriber, the dispatch
is a no-op (HA's dispatcher tolerates zero receivers). When presence's
`async_setup` runs later, `OccupancySubstrate.async_setup()` already
enumerates all currently-loaded ROOM entries — so the room joins on
cold-boot via the existing full-enumeration path. The signal path is for
the LATE-add case.

**Teardown symmetry.** ROOM unload dispatches
`action="unloaded"`. Substrate refresh diffs, tears down the old
listener first (safe: no rooms use that entity anymore), then registers
the smaller listener over the surviving set. Same atomic-swap discipline
as add.

**Bug Class #50 guardrail.** The substrate's OWN unsub is stored in
`self._unsub_listeners` (`occupancy_substrate.py:275`). No external code
clears this list. `refresh_subscriptions()` is the ONLY caller that
rewrites it, and it does so atomically. We MUST NOT store the new
subscription in any list that a periodic rebuild elsewhere clears.

---

## Deliverables

### D1: New signal `SIGNAL_ROOM_ENTRY_LIFECYCLE`

Add to `domain_coordinators/signals.py`. Payload: `(entry_id, room_name,
action)`. Fired from three sites in `__init__.py`:

- ROOM `async_setup_entry` after coordinator stored (`__init__.py:~3476`).
- ROOM unload path (locate matching `async_unload_entry` for ROOM entries).
- `_async_update_listener` ROOM branch when suppressed OR after reload
  (fire-once at settle).

**Acceptance:**
- **Verify:** grep proves exactly 3 dispatch sites; each passes the
  correct `action` string.
- **Test:** unit test asserts signal fires with `{room_name, entry_id,
  action}` payload on each transition.

### D2: `OccupancySubstrate.refresh_subscriptions()` coroutine

New public method on `OccupancySubstrate`. Diff-based re-enumeration +
atomic swap per Design section. Idempotent — safe under rapid
successive calls (e.g. two rooms loading back-to-back).

**Acceptance:**
- **Verify:** old unsub called exactly once per swap; new unsub captured
  before old is released (log line ordering).
- **Test:** `test_refresh_subscriptions_adds_new_room` — add a ROOM
  entry after substrate setup, fire the new room's motion sensor via
  `hass.states.async_set`, assert `SIGNAL_SUBSTRATE_KIND_CHANGED`
  dispatches WITHIN a single event-loop tick, WITHOUT invoking any
  polling coordinator refresh.
- **Test:** `test_refresh_subscriptions_removes_stale_room` — remove a
  ROOM, fire the removed sensor, assert zero substrate dispatches AND
  zero KeyError / stale `_raw_state`.
- **Test:** `test_refresh_subscriptions_edits_sensor_list` — update
  ROOM options to add a new motion sensor, assert the new sensor lands
  in `_entity_to_room_kind` and its edge dispatches.
- **Test:** `test_refresh_atomic_swap_no_double_dispatch` — inject an
  in-flight state-change during swap; assert exactly one dispatch on
  the changed edge.
- **Test (historical regression pin):**
  `test_room_added_after_substrate_setup_is_event_driven` — reproduces
  the Master Bath Toilet scenario. Substrate setup completes; then a
  new ROOM entry is added; motion edge is observed within one event-
  loop tick with no polling coordinator refresh. This test is the
  regression pin against re-shipping v4.7.24's blind spot.

### D3: PresenceCoordinator subscription

Subscribe `PresenceCoordinator` to `SIGNAL_ROOM_ENTRY_LIFECYCLE` in
`async_setup` (immediately after `self._substrate.async_setup()` at
`presence.py:~2192`). Handler calls `await
self._substrate.refresh_subscriptions()`. Unsub tracked in
`self._unsub_listeners` (NOT touched by any periodic rebuild —
verified).

**Acceptance:**
- **Verify:** unsub appended to `_unsub_listeners`; released on
  `async_teardown`.
- **Test:** presence-coordinator teardown → refresh signal → no leak.

### D4: Canary log when a room-coordinator poll delivers an edge for a sensor that SHOULD be substrate-subscribed

In the room coordinator's poll path (`coordinator.py:992-1031`
`_trigger_rate_limited_refresh` neighborhood), when a poll cycle
detects a motion/mmwave/occupancy sensor edge, cross-check
`hass.data[DOMAIN]["occupancy_substrate"]._entity_to_room_kind` — if
the entity SHOULD be tracked (present in the room's CONF lists) but
ISN'T in the map, log ONE WARN per (room, entity) with
`_LOGGER.warning`. Rate-limited via a set on the coordinator to avoid
log spam. Scope: ~20 LoC. Cheap. Ships.

**Acceptance:**
- **Verify:** log fires exactly once per (room, entity) even under
  sustained poll deliveries.
- **Test:** `test_substrate_gap_canary_logs_once` — construct a room
  whose substrate map is artificially empty; simulate poll edges;
  assert one WARN.
- **Live:** grep HA log for `substrate gap` after any post-onboard
  cycle — zero occurrences post-fix; would have fired repeatedly
  against the pre-fix Master Bath Toilet scenario.

### D5: Live-validation criteria (post-restart)

Cycle is not closed until this table is written back into the README:

- **Live:** onboard-a-room-without-restart flow —
  1. Create a new ROOM entry (e.g. "Test Room") via config-flow with
     at least one motion sensor CONFed.
  2. Within 10s of entry `state=loaded`, fire the motion sensor and
     check:
     - `sensor.<room>_occupancy` transitions to `occupied` in **<3s**
       (matches pre-onboard sibling-room latency of ~1.5-2s within
       noise).
     - No `substrate gap` WARN in log (D4 canary silent).
     - `hass.data[DOMAIN]["occupancy_substrate"]._entity_to_room_kind`
       includes the new sensor (introspect via a diagnostic sensor if
       already exposed, else via Python shell / test hook).
  3. Edit the ROOM options to add a second motion sensor; repeat.
  4. Remove the ROOM entry; assert zero stale dispatches (grep for
     the removed sensor name in `SIGNAL_SUBSTRATE_KIND_CHANGED` log
     lines after removal — zero).

---

## Tier classification

**Tier 2-DB (standing policy).** Substrate is a shared primitive
consumed by room-tier (`coordinator.py:1040`), zone-tier
(`presence.py:2212`), and transitively house-state. This is also a
regression restoration — the burden of proof includes showing that the
pre-June-5 event-driven onboarding guarantee is back.

**Three framing-disjoint reviews:**

- **A — Diff correctness + edge semantics.** The atomic swap logic.
  Verify `added`/`removed`/`re-classified` set math handles: same
  entity reassigned across rooms; same entity moved between kinds;
  entity in multiple CONF lists (existing precedence). Verify seed-on-
  add matches the seed logic in `async_setup` byte-for-byte. Verify
  Bug Class #38 discipline preserved (every unsub called exactly
  once).
- **B — Lifecycle + ordering + concurrency.** ROOM entry loaded before
  presence coordinator is set up (cold-boot ordering). Two rooms load
  back-to-back — refresh coalescing / re-entrancy. Options-save fires
  refresh during an in-flight refresh. Unload during refresh. Bug
  Class #50 recurrence audit on the substrate's own unsub list.
  Teardown symmetry.
- **C — Adversarial completeness / dispatch-gap falsification.** Sole
  job: state the invariant (above) and break it. Reviewer C enumerates
  ALL paths that mutate the substrate's entity set — including any
  code path in `_async_update_listener` that could bypass the new
  signal — and constructs a legal-config scenario where a real edge is
  lost or double-fired during swap. This reviewer also verifies the
  historical-regression pin test (D2 last bullet) actually fails on a
  neuter of the new signal wiring.

---

## Risks

- **R1 (medium).** Atomic-swap ordering is subtle. Registering the new
  listener before releasing the old creates an overlap window where
  BOTH fire for surviving entities. Idempotence at
  `_handle_state_change` (`:383-384`) neutralizes this AT THE PER-KIND
  BOOL EDGE — but a rapid off→on→off during the overlap window could
  still emit only one edge if the second listener is registered mid-
  flight. Mitigation: swap ordering test with injected concurrent
  event.
- **R2 (low).** ROOM `async_setup_entry` fires the signal even if the
  presence coordinator later fails to set up. Handler simply never
  runs — same behavior as pre-fix. No leak.
- **R3 (low).** Options-flow suppressed writes (currently only comfort
  sliders) fire the signal unnecessarily → substrate re-enumerates
  and diffs to zero-change. Cost: one enumeration walk per slider
  drag. Cheap; keep for future-proofing.
- **R4 (low).** Canary log (D4) could fire during the substrate's own
  swap window if a poll happens to land in that ~ms window. Rate-
  limit set handles it; the first spurious WARN per (room, entity) is
  tolerable and makes the canary honest.

---

## Recommendations for `docs/QUALITY_CONTEXT.md`

Propose a NEW bug class capturing the v4.7.24 lesson (draft language;
reviewer finalizes):

> **Bug Class #NN — Centralized-subscription regression: per-entry
> lifecycle hook lost.** When per-entry state-change subscriptions are
> centralized into a shared primitive built once at parent-coordinator
> setup, the parent MUST subscribe to a per-entry lifecycle signal
> (add/remove/options-update) and re-invoke the primitive's discovery
> path. Otherwise entries created after parent setup silently degrade
> to poll latency. Guard with a test that adds a ROOM entry AFTER the
> centralized setup completes and asserts event-driven behavior on the
> new entry within one event-loop tick.
> Exemplar: substrate unification v4.7.24 → 2026-07-10 fix cycle
> (Master Bath Toilet 34s latch vs 1.5s sibling rooms).

---

## Backward-compatibility

- Signal is additive. Cold-boot path is unchanged (substrate still
  enumerates all loaded entries at `async_setup`).
- No config-flow / options-flow schema changes.
- No new CONF_*, Number, Sensor, or Select entities.
- No DB schema changes.

---

## Verification checklist (pre-review)

- [ ] Grep proves substrate `_unsub_listeners` never touched outside
      `_teardown_listeners` / `refresh_subscriptions` / `async_setup`.
- [ ] Grep proves `SIGNAL_ROOM_ENTRY_LIFECYCLE` dispatch count = 3, all
      in `__init__.py`.
- [ ] All D2 tests fail on a build that skips the atomic-swap (single
      mutation).
- [ ] Historical-regression pin test fails on a neuter that drops the
      new signal handler.
- [ ] Presence coordinator `_unsub_listeners` list is not cleared by
      any periodic rebuild (Bug Class #50 audit).
