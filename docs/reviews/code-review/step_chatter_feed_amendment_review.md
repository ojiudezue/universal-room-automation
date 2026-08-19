# Plan-review — STEP chatter-feed amendment (Option 1: own listener)

**Scope:** ONLY the 2026-08-19 amendment to `docs/planning/PLANNING_sensor_health_surfacing.md` §D2
that switches the ChatterDetector from `OccupancySubstrate.subscribe()` to owning its own
`async_track_state_change_event` per-entity listener. Everything else in the plan (§0-§3, D1,
D1.1, definition, provenance classifier, knobs, D3-D6) is out of scope — previously reviewed
PLAN-READY.

**Verdict: PLAN-READY.** One LOW finding recorded; not blocking build dispatch.
Amendment is correct, necessary, and does not open a new gap.

---

## Verification (greps, not trust)

### 1. Feed-shape diagnosis is correct — CONFIRMED

`custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py:704-706`:

```python
for cb in list(self._local_subscribers):
    try:
        cb(room_name, kind, new_state)
```

and the type at `:764-767`:

```python
def subscribe(
    self,
    cb: Callable[[str, str, bool], None],
) -> Callable[[], None]:
```

The `subscribe()` fan-out delivers `(room, kind, new_state)` — a **per-KIND aggregate** edge, not
per-entity. When two motion sensors of the same kind fire in the same tick the substrate OR's them
into one bucket and dispatches a single `(room, "motion", True)`; the offending entity's
`entity_id` is lost before the callback fires. A sub-`T_floor` burst counter that needs to attribute
individual transitions to individual entities CANNOT be built on this feed. Option 1 (own
`async_track_state_change_event`) is genuinely necessary, not an over-correction.

### 2. `async_track_state_change_event` API usage is correct — CONFIRMED

Existing pattern at `coordinator.py:1350-1352`:

```python
async_track_state_change_event(
    self.hass, [lux_entity], _on_lux_state_changed,
)
```

matches the plan's registration `async_track_state_change_event(hass, list(entity_ids),
self._on_edge)`. The callback signature in the amendment (§D2 `_on_edge(event)` skeleton) uses
`event.data.get("entity_id")`, `event.data.get("new_state")`, and `event.time_fired` — all three
are on HA's `Event` object for `state_changed` events (the pattern at `coordinator.py:1340-1346`
uses the same `event.data.get("new_state")` / `event.data.get("old_state")` shape and
`event.time_fired` is a documented `homeassistant.core.Event` attribute of type
`datetime.datetime`). No API mismatch a builder would hit.

Guarding `if new_state is None or new_state.state in ("unavailable", "unknown"): return` is
correct — state-change events fire on `unavailable` transitions and those are explicitly excluded
from chatter counting (§D2 algorithm skeleton step 2).

### 3. entity_id → kind derivation is sound — CONFIRMED (staleness → LOW below)

The inversion of `_KIND_TO_CONF` at `occupancy_substrate.py:82-86` plus the opener CONF is well-defined
and one-shot at setup. Every entity that survives the `CHATTER_PROVENANCE_ALLOWLIST` gate is by
construction in exactly one of the room's `CONF_*_SENSORS` lists, so the map covers the listener
domain. The defensive `if kind is None: return` in `_on_edge` is belt-and-suspenders (listener set
== inversion domain).

Staleness under options-flow reload: URA room-entry reloads teardown-and-reconstruct their
RoomCoordinator (established pattern — CM has reload-suppression, room entries do not; verified via
the plan's own §9 Review B charter "no leaked HA listener survives a room-entry reload"). On reload,
`ChatterDetector.async_teardown()` fires (calls `self._chatter_unsub()`, clears map), then the new
detector's `async_setup()` rebuilds `_entity_to_kind` from the (edited) CONF lists. No stale-map
gap in practice.

**LOW-1 (staleness precondition made implicit, not explicit):** the plan does not state that
`_entity_to_kind` refresh relies on room-entry reload lifecycle. Reviewer D §9(viii) is charged
with enumerating this hazard, which is good, but a one-line reassurance in §D2 ("the map is a
one-shot setup-time build; it refreshes when the room entry reloads on options edits — same
lifecycle that recreates every other coordinator listener") would prevent a future refactor
mistakenly making `_entity_to_kind` a long-lived module-level cache. Non-blocking; recommend the
builder add the line, or Reviewer B flags it during Tier-3 review.

### 4. Teardown test is genuinely real, not fictional — CONFIRMED

Amendment §D2 "Subscribe lifecycle" specifies:

- `self._chatter_unsub` = the callable RETURNED BY `async_track_state_change_event`, i.e. the
  HA-owned unsub, not a URA-internal callback-list entry.
- `async_teardown()` calls `self._chatter_unsub()` if set and clears the ref.
- `test_chatter_detector_unsubscribe_called_on_teardown` spies the mock hass's
  `async_track_state_change_event` return value (a Mock callable), stores the spy, invokes
  `async_will_remove_from_hass()`, and asserts the Mock was invoked exactly once.
- §D6 test 7 mutates the source to DELETE the `self._chatter_unsub()` call; the lifecycle test
  MUST red (the Mock records zero calls).

This is a real Bug Class #38 anchor. The prior framing (spying a URA-internal subscribe callback
list, whose unsub was semantically equivalent to `list.remove`) would have been hollow because it
proved only that URA's own bookkeeping cleaned up, not that HA's listener registry actually
released the callback. The amendment fixes this.

### 5. Entity-set gating consistent with classifier — CONFIRMED

Amendment: "The entity set = the room's Tier-1 sensors filtered to `(kind, provider)` tuples in
`CHATTER_PROVENANCE_ALLOWLIST`… Cameras / AI / aggregates / bed-multistate are excluded at
set-construction time (they are also denied by the classifier at scoring time; excluding them
from the listener set means the listener never fires on them and the classifier DENY is defense in
depth)."

`binarygroup_camera_motion_zone1` is thus never registered on the listener AND separately DENIED
by the classifier. Defense-in-depth is consistent with M-MED-2 semantics; the invariant
(camera-motion group receives zero chatter promotions) holds by both mechanisms.

Empty-set case handled: `self._chatter_unsub = None` when the room has no blind-time-gated
sensors; `async_teardown()`'s `if set` guard prevents a None-call. Correct.

### 6. No new gap / scope creep — CONFIRMED

- `occupancy_substrate.py` remains untouched (§8 "No changes to" explicitly names it, strengthened
  under this amendment). The substrate keeps its per-kind semantics; no `subscribe_entities()` API
  is being smuggled in (§10 explicitly parks that as a separate future work).
- Duplicate listen with `coordinator.py:1350` (lux) is acknowledged as intentional and benign;
  HA dispatches natively; per-room cost is one extra registration per blind-time-gated entity.
- §D1.1 ordering (reset_tick → _prev_excluded snapshot → P22 → STUCK-SENSOR-1 → chatter) is
  unaffected: the chatter promotion block still runs at the tick site, immediately after the
  STUCK-1 D1 loop, consuming a `_chattering_entities` set the detector accumulated ASYNCHRONOUSLY
  from HA state-change events between ticks. The tick-site reads a snapshot; there is no coupling
  between the async listener and D1.1's synchronous release-scan bookkeeping.
- Non-goal 12 (§6) and §7 Producer check are already updated to match. No section is silently
  broken by the amendment.

---

## Findings

| ID | Severity | Blocking | Summary |
|---|---|---|---|
| LOW-1 | LOW | No | `_entity_to_kind` refresh mechanism is implicit (relies on room-entry reload lifecycle). One-line reassurance in §D2 recommended so a future refactor doesn't cache the map beyond a single setup. Reviewer D §9(viii) already charged with enumerating; not blocking. |

No CRITICAL, no HIGH, no MEDIUM. No API mismatch. No broken entity_id→kind derivation. No stale-map
gap that isn't handled by lifecycle. Teardown test is real.

---

## Verdict

**PLAN-READY** for Tier-3 build dispatch under the §9 four-framing-disjoint protocol.

The feed amendment is correct: `OccupancySubstrate.subscribe()` genuinely cannot power the chatter
burst counter (per-KIND aggregate), Option 1's own `async_track_state_change_event` registration
uses the HA API correctly and matches the existing in-repo pattern, the entity_id→kind derivation
inverts a stable one-shot constant, and the teardown assertion now targets the HA-returned unsub
callable (not a URA-internal bookkeeping proxy).

LOW-1 may be folded into the builder's brief or handled by Reviewer B during Tier-3 review.
