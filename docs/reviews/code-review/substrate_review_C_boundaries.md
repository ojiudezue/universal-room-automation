# Code Review C — Occupancy Substrate Unification

**Reviewer framing:** Boundary cleanliness + test-fixture authority + consumer-migration audit.
**Risk axis:** "right data, wrong downstream wiring / non-authoritative tests."
**Branch:** `feature/occupancy-substrate-unification`
**Diff base:** `develop` (commits: `fb7d195` plan, `e165e1c` build).
**Files audited (verified via direct read):**

- `custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py`
- `custom_components/universal_room_automation/domain_coordinators/__init__.py`
- `custom_components/universal_room_automation/domain_coordinators/signals.py`
- `custom_components/universal_room_automation/domain_coordinators/presence.py` (`:1700-1740, 1880-1940, 2285-2453, 3280-3340, 5305-5325`)
- `custom_components/universal_room_automation/coordinator.py` (`:120-130, 895-1040, 2290-2320`)
- `custom_components/universal_room_automation/binary_sensor.py` (`:540-575`)
- `quality/tests/test_substrate_*.py` (all 6 new files)
- `quality/tests/test_zone_substrate_migration.py`
- `quality/tests/test_room_substrate_integration.py`
- `quality/tests/test_substrate_backcompat.py`
- `quality/tests/test_v47181_sleep_wake_deadlock.py` (lockstep edit)
- `docs/Coordinator/PRESENCE_COORDINATOR.md`, `docs/Coordinator/COORDINATOR_ARCHITECTURE.md`
- `docs/planning/AUDIT_occupancy_substrate_consumer_ripple.md`

---

## Verdict: **FIX-THEN-SHIP**

The boundary structure (module ownership, API surface, signal naming, public
export) is clean and matches D1 spec. The consumer-migration audit found one
missing audit-table entry (`sensor.py::_zone_provenance_breakdown`) and one
silent data-corruption risk for multi-room duplicate entity_ids. The biggest
class of findings is **test-fixture authority**: four of the new tests
(including the D4 FanRecheck cross-check that Review C was specifically asked
to verify) either re-implement the assertion against themselves or use
source-grep instead of driving production code paths. None of the findings is
data-correctness-blocking for the live deploy, but the test suite as it stands
gives weaker regression coverage than the planning doc claims, and the
lockstep edit to `test_v47181_sleep_wake_deadlock.py` weakened the
v4.7.18.1 B-HIGH-1 invariant via an `or` substring fallback. Fix the listed
HIGH items, then ship.

---

## Findings

### HIGH-1 — `test_substrate_backcompat.py` is a tautology; the D4 FanRecheck cross-check is not actually exercised

**File:line:** `quality/tests/test_substrate_backcompat.py:46-65, 110-129`
**Bug class:** Test-fixture authority (Tier 2-DB review C-C1 family — "behavioral test fixtures must DRIVE production code paths, not their own copy of the logic").

Both `_drive_pre_substrate_flow` and `_drive_substrate_flow` are
**bit-identical**:

```python
def _drive_pre_substrate_flow(tracker, sequence):
    for room, occ, kind in sequence:
        tracker.update_room_occupancy(room, occ, kind=kind)

def _drive_substrate_flow(tracker, sequence):
    for room, occ, kind in sequence:
        tracker.update_room_occupancy(room, occ, kind=kind)
```

Every assertion is therefore `X == X`. The "pre" path does NOT replay the
pre-substrate code (which would have classified via
`_classify_entity_kind_cached` from the state-change event), and the "post"
path does NOT drive a real `OccupancySubstrate` instance through
`_handle_state_change` → `async_dispatcher_send` →
`_on_substrate_kind_changed` → `tracker.update_room_occupancy`.

The plan's D4 acceptance explicitly required:

> Test (FanRecheck cross-check): `test_substrate_backcompat.py` includes a
> case driving a substrate-mediated `STATE_OCCUPANCY_SOURCE` transition
> and asserting `recent_occupancy_sources()` + the FanRecheck eligibility
> read (`_is_eligible` / `_on_pause_window_done` consumption of
> `occupancy_source` / `occupied` / `presence_detected`) see IDENTICAL
> values pre- and post-substrate.

Neither `STATE_OCCUPANCY_SOURCE`, `recent_occupancy_sources()`, the
`FanRecheckManager`, nor any `coordinator.data` field appears anywhere in
the test body. The test only ever calls `tracker.update_room_occupancy`
on a `ZonePresenceTracker` — which is the SAME call shape it always was —
and asserts equality with itself.

**Concrete fix.** Replace with a fixture that:

1. Instantiates `OccupancySubstrate(hass)`, drives a sequence of
   state-change events via `_handle_state_change` and `release_boot_settle`.
2. Asserts the resulting `SIGNAL_SUBSTRATE_KIND_CHANGED` dispatches are
   absorbed by a wired `_on_substrate_kind_changed` callable that writes
   into a real `ZonePresenceTracker`.
3. For the FanRecheck row: instantiate a minimal `UniversalRoomCoordinator`
   surrogate that runs `_async_update_data` and produces a
   `STATE_OCCUPANCY_SOURCE` value, then assert `recent_occupancy_sources()`
   contains the expected sequence after driving substrate edges. Alternatively,
   if a full coordinator surrogate is too heavy, at minimum drive
   `data[STATE_OCCUPANCY_SOURCE]` synthetically through the room-tier
   flat-OR helper and pin the resulting `recent_occupancy_sources()` ring.

Without this fix, the v4.7.22 FanRecheck regression that the D4 audit
promised is "covered by test" is effectively uncovered. If a future
refactor of `_on_substrate_kind_changed` accidentally swallowed the
`kind` kwarg, the existing test would still pass.

---

### HIGH-2 — `test_room_substrate_integration.py` is source-grep, not behavioral

**File:line:** `quality/tests/test_room_substrate_integration.py:23-78`
**Bug class:** Test-fixture authority (Tier 2-DB review C-C1 family).

All three tests open `coordinator.py` and assert string substrings exist
in the source. They do NOT instantiate `UniversalRoomCoordinator`, do NOT
fire a `SIGNAL_SUBSTRATE_KIND_CHANGED` dispatch, and do NOT verify the
rate-limiter behavior or the immediate-`async_refresh()` decision. This is
explicitly the C-HIGH-1 "substring assertion would silently pass on a
hard-coded literal rewrite" category that the v4.7.18.1 review codified.

In particular, `test_coordinator_preserves_rate_limiter` asserts
`"now_mono - self._last_event_refresh < 2.0" in src`. If the rate-limiter
constant moves from a magic number to a named constant (e.g., a defensible
refactor), or the operator deflates it to 1.0 in a future patch, this
test silently passes while production breaks.

The plan D3 risk list explicitly called this out: *"actuation-path
immediate-refresh listener rewire... Reviewer B owns this trace
end-to-end."* The build then shipped Reviewer B's coverage as a source-grep,
which doesn't satisfy the stated review-coverage obligation.

**Concrete fix.** Drive a real signal through `async_dispatcher_send` in
an integration test with a mocked `UniversalRoomCoordinator`. At minimum,
assert:
1. `_trigger_rate_limited_refresh` was called when a substrate dispatch
   matched the room.
2. `_trigger_rate_limited_refresh` was NOT called when the substrate
   dispatch was for a different room.
3. The lux state-change still triggers the rate-limited refresh.

These are three asserts on observable behavior, not on string presence.

---

### HIGH-3 — Lockstep edit to `test_v47181_sleep_wake_deadlock.py` weakens the B-HIGH-1 invariant via `or` fallback

**File:line:** `quality/tests/test_v47181_sleep_wake_deadlock.py:626-642` (post-diff)
**Bug class:** Test-fixture authority (regression: explicit re-occurrence of the v4.7.18.1 C-HIGH-1 substring-loosening hazard).

The rewrite's final assertion reads:

```python
seed_call_re = re.compile(
    r"tracker\.update_room_occupancy\("
    r"\s*room_name\s*,"
    r"\s*True"
    r"(?:\s*,\s*kind\s*=\s*\w+)?"
    r"\s*,?\s*\)"
)
assert seed_call_re.search(body) or "update_room_occupancy(" in body, (
    "v4.7.18.1 + substrate: zone-tier _discover_room_sensors must "
    "seed the tracker via update_room_occupancy from the substrate "
    "snapshot"
)
```

The `or "update_room_occupancy(" in body` clause makes the assertion pass
**so long as the method name appears anywhere in the function body** — which
includes the unrelated `else` branch that also calls `update_room_occupancy`
(the False-default at presence.py:2414). The regex itself is well-targeted,
but the `or` fallback nullifies it. This is the same C-HIGH-1 pattern the
v4.7.18.1 review explicitly hardened against in the test that this rewrite
just modified.

The prior assertion used a tighter regex anchored to `occupied` (the seeded
boolean), and the substrate moved the invariant from "seed the entity's
current `occupied` value" to "seed only True-slot kinds from the substrate
snapshot, write False once when nothing is True." The new regex correctly
encodes the new shape; the `or` fallback re-loosens it.

Separately, the substrate-side half of the test (lines 595-606 in the new
file) asserts `"self.hass.states.get(entity_id)" in substrate_src`, which is
correct but susceptible to the same substring-rewrite hazard. A defensive
fix uses a regex that pins the surrounding context (e.g., the for-loop
header reading `for entity_id, kind in entity_map.items()`).

**Concrete fix.** Delete the `or "update_room_occupancy(" in body` clause.
If the regex needs widening for legitimate refactors, widen the regex —
don't substring-fallback.

---

### MEDIUM-1 — `_zone_provenance_breakdown` consumer missing from D4 audit table

**File:line:** `custom_components/universal_room_automation/sensor.py:3977-4000`
**Bug class:** Consumer-migration audit completeness (Tier 2-DB review C-3).

`_zone_provenance_breakdown(tracker)` reads
`getattr(tracker, "_room_provenance", {}).items()` and is exposed on at
least one diagnostic sensor surface. It is NOT in
`PLANNING_occupancy_substrate_unification.md` § D4 or in
`AUDIT_occupancy_substrate_consumer_ripple.md`. Behavior is unchanged
post-substrate (the substrate continues to feed `_room_provenance` via
`tracker.update_room_occupancy` with the same `kind` slot), but the
review C charter required surfacing exactly this kind of unlisted
consumer.

The data-quality improvement here is real: in the pre-substrate Jaya
case, area-sweep-superset sensors would land in `_room_provenance`
slots whose kind was assigned by the substring classifier; post-substrate,
the kind is the CONF-slot kind for the curated 2 sensors, and the
breakdown counts are operator-intended. Worth flagging as IMPROVED so
the operator knows the diagnostic surface tightened.

**Concrete fix.** Add the row to
`docs/planning/AUDIT_occupancy_substrate_consumer_ripple.md` with
verdict "improved — slot kinds now match CONF list intent." No code
change required.

---

### MEDIUM-2 — `_entity_to_room_kind` silently last-room-wins for cross-room duplicate entity_ids

**File:line:** `custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py:232`
**Bug class:** Defensive operator-config validation (no QC bug class number — closest sibling is the v4.7.5 Bug Class #47 canonical-resolution family).

```python
self._entity_to_room_kind[entity_id] = (room_name, kind)
```

If the operator (defensively, mistakenly) lists `binary_sensor.x` in
Room A's `CONF_MOTION_SENSORS` AND Room B's `CONF_MMWAVE_SENSORS`, the
substrate's per-room WARN at lines 197-202 fires ONLY for same-room
multi-list — there is no log when the second room overwrites the
first. Result: edges on that entity dispatch to whichever room won the
iteration order, silently dropping the other room. The
`_handle_state_change` callback reads from this map, so the room-tier
sensor for the silently-dropped room never sees the edge.

Probability is low (operator configs don't normally do this), and the
substrate cycle exists precisely to surface configuration divergence —
so silently losing one room is the WORST kind of divergence to hide.

**Concrete fix.** Before the assignment, check if `entity_id` is already
in `_entity_to_room_kind` with a different `room_name`; if so, WARN with
both rooms and keep the first (declared-iteration-order — stable for the
operator). This is ~6 LoC; safe to fold into the same fix-up pass.

---

### MEDIUM-3 — Post-substrate inference-cycle cadence may differ from pre-substrate on no-op state events

**File:line:**
`custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py:367-373`
combined with `presence.py:2452` (`_run_inference("occupancy_change")`)
**Bug class:** Observable behavior change (sibling to QC #38 in spirit).

Pre-substrate: `_handle_occupancy_change` ran `_run_inference` on every
state-change event for a registered occupancy entity (including attribute-
only updates where state did not actually change). Post-substrate:
`_on_substrate_kind_changed` fires inference only on true bool edges
(the substrate early-returns at `prior == occupied`). This is *probably*
benign (inference is idempotent against attribute-only changes) and
arguably an improvement, but it is a measurable cadence change in a
hot-path callback that the planning doc did not call out.

**Concrete fix.** Two options, in preference order:
1. Document the change in the D4 audit table as "improved — inference
   no longer fires on attribute-only state events." Acceptable if the
   builder has confirmed no inference path observes side effects on
   attribute-only events.
2. Lower the threshold in `_handle_state_change` to dispatch on every
   `new_state.state == "on"` (matching the prior cadence) at the cost
   of more dispatcher traffic. NOT recommended.

---

### MEDIUM-4 — Synthetic settle-replay dispatches add a new cold-boot refresh burst on the room tier

**File:line:**
`occupancy_substrate.py:303-326` (release_boot_settle) +
`coordinator.py:965-984` (room-tier handler) +
`coordinator.py:945-961` (`_trigger_rate_limited_refresh`).
**Bug class:** Cold-boot-storm interaction (related to the v4.7.21
boot-settle work).

At settle, `release_boot_settle()` emits one synthetic
`SIGNAL_SUBSTRATE_KIND_CHANGED` per (room, kind) True-slot. The room-tier
handler at `coordinator.py:978-984` filters by room and calls
`_trigger_rate_limited_refresh()` for matches — which schedules an
`async_refresh()` (or queues a trailing-edge refresh if within the 2s
window). Pre-substrate, the room-tier seed loop did NOT trigger
`async_refresh()` — the seeding happened during async_setup BEFORE the
listener was registered.

So at settle, every room with at least one True-seeded kind now fires
an `async_refresh()` it didn't fire pre-substrate. The 2s rate limiter
caps the rate per room, but it is still a new burst that fights — or
coordinates with, depending on luck — the v4.7.21 boot-settle gates in
`presence.py:1898` (Predicate A `real_input`) and the HVAC Gate 2
holds.

Probability of regression: LOW. Refresh is idempotent and rate-limited.
But this is exactly the seam the v4.7.21 cycle hardened against, so it
needs eyes-on the boot logs after deploy.

**Concrete fix.** Two acceptable mitigations:
1. **(Preferred)** Have `_on_substrate_kind_changed` in `coordinator.py`
   skip `_trigger_rate_limited_refresh()` if the room-tier
   `_boot_settle_done` (or coordinator equivalent) is not yet released.
   Document the gate-skip in `coordinator.py` next to the substrate
   subscription block.
2. Live validation note: post-deploy, verify the room-tier refresh
   counts at boot+settle do not exceed pre-cycle baselines by more than
   N per room (N = number of True-seeded kinds at settle). Add to the
   live-validation script.

---

### LOW-1 — Function-local imports inside `PresenceCoordinator.async_setup` (presence.py:1894, 1918, 1921)

**File:line:**
`custom_components/universal_room_automation/domain_coordinators/presence.py:1894, 1918, 1921`
**Bug class:** QC #34 family (function-local imports — though this is the
benign sub-case, NOT the v4.7.20.1 recurrence pattern).

```python
from .occupancy_substrate import OccupancySubstrate  # noqa: PLC0415
from homeassistant.helpers.dispatcher import (  # noqa: PLC0415
    async_dispatcher_connect,
)
from .signals import (  # noqa: PLC0415
    SIGNAL_SUBSTRATE_KIND_CHANGED,
)
```

These are inside `async def async_setup`, NOT inside a `@callback`, and
they are unconditional. They do NOT trigger Bug Class #34's
`UnboundLocalError` failure mode. However, the substrate's own module
docstring + the planning doc both pin "no function-local imports" as a
substrate-cycle invariant, and `coordinator.py` does the import at
module-top (`coordinator.py:124`). The asymmetry is cosmetic but worth
unifying.

**Concrete fix.** Move all three imports to module-top in `presence.py`.
~6 LoC, zero behavior change.

---

### LOW-2 — Docs / build divergence: D7 file table lists `__init__.py` as wiring substrate, but the wiring is inside `presence.py::async_setup`

**File:line:** `docs/planning/PLANNING_occupancy_substrate_unification.md` D7 table
**Bug class:** Doc drift.

The D7 table reads:

> `__init__.py` | Wire substrate instantiation on PresenceCoordinator setup; teardown on unload.

The actual implementation wires substrate inside
`PresenceCoordinator.async_setup` (`presence.py:1894-1929`) and tears it
down inside `PresenceCoordinator.async_teardown` (`presence.py:5315-5323`).
The `custom_components/universal_room_automation/__init__.py` contains
ZERO references to `OccupancySubstrate`. This is arguably the cleaner
architecture (lifecycle co-located with owner), but the plan-vs-code
divergence will confuse a future reviewer or operator.

**Concrete fix.** Update D7 to read:
> `domain_coordinators/presence.py` | INSTANTIATE substrate in
> `PresenceCoordinator.async_setup` (before `_discover_room_sensors`);
> TEAR DOWN in `async_teardown` before `_cancel_listeners`.

Update D8 (plan completion tracking) noting the relocation.

---

### LOW-3 — `_handle_occupancy_change` is dead code post-substrate

**File:line:**
`custom_components/universal_room_automation/domain_coordinators/presence.py:3286-3335`
**Bug class:** Code hygiene.

`_handle_occupancy_change` is no longer subscribed to anything (verified
via grep: no `async_track_state_change_event(..., self._handle_occupancy_change)`
call survives the diff). Its docstring references the pre-substrate
listener path. The deletion comment at `:3326-3333` correctly explains
why the name-based fallback inside this function was removed — but the
function itself is now orphan and only referenced by comments / docstrings
elsewhere in the file.

The function does NOT cause a bug (it can't be called), but it makes
future readers wonder "is this still subscribed somewhere?" and
muddies the migration story.

**Concrete fix.** Delete the function body (`presence.py:3285-3335`) and
update the cross-references in `presence.py:676, 2309, 2450, 2702, 3670`
to point at `_on_substrate_kind_changed` instead. ~50 LoC removal.
Acceptable to defer to a follow-up hotfix if the operator wants this
cycle's diff to stay minimal — but track it.

---

### LOW-4 — `test_zone_substrate_migration.py` claim "Simulate the substrate-driven path" is misleading

**File:line:** `quality/tests/test_zone_substrate_migration.py:27-29`
**Bug class:** Test fixture authority (cosmetic — does NOT weaken the
actual zone-tier behavior asserted, but the comment misleads).

The test calls `tracker.update_room_occupancy(...)` directly, which the
comment describes as "Simulate the substrate-driven path." The actual
substrate-driven path goes through `async_dispatcher_send` →
`_on_substrate_kind_changed` → `tracker.update_room_occupancy`. The test
correctly asserts the **post-tracker** invariants (provenance shape +
raw_occupied freshness) which are unchanged — that's fine — but
"simulate the substrate-driven path" overstates what's being tested.

**Concrete fix.** Either:
1. Rewrite the comment to "Drive the same tracker call shape that
   `_on_substrate_kind_changed` produces."
2. Add a separate test that wires a real substrate dispatch through a
   minimal `PresenceCoordinator` surrogate to `_on_substrate_kind_changed`
   and asserts the tracker state.

Prefer (2) — would also strengthen HIGH-1's gap.

---

## Sign-off

- **Module boundary:** clean. `OccupancySubstrate` lives in
  `domain_coordinators/occupancy_substrate.py`, exported via
  `domain_coordinators/__init__.py`, lifecycle owned by `PresenceCoordinator`
  (cleaner than the plan's D7 claim of `__init__.py`; treat the docs as
  drifted, not the code as wrong). No circular import between `presence.py`
  and `occupancy_substrate.py` (the substrate imports zero presence
  modules). API surface matches D1 spec exactly.
- **Consumer-migration audit:** D4 table is complete except for the
  `_zone_provenance_breakdown` sensor diagnostic (MEDIUM-1) and the
  cross-room duplicate-entity edge case (MEDIUM-2). FanRecheck reads via
  `STATE_OCCUPANCY_SOURCE` flat-OR are preserved by construction at
  `coordinator.py:1476-1480` (verified). `recent_occupancy_sources()` ring
  shape unchanged.
- **`substrate_kinds` lazy attr:** correctly fail-open at
  `binary_sensor.py:555-573`; defaults to `{k: False for k in TIER1_KINDS}`
  on any exception. Round-trip safe.
- **Test-fixture authority:** weak. HIGH-1 (backcompat tautology), HIGH-2
  (room-integration source-grep only), HIGH-3 (lockstep edit reintroduced
  the substring-loosening hazard) all need fixes before the next deploy.
- **v4.7.18.1 B-HIGH-1 seed invariant:** preserved in the substrate's
  `async_setup` seed loop AND in the thin `_discover_room_sensors` body
  that seeds the zone-tier tracker from the substrate snapshot. The
  invariant truly moved; the test that pins it weakened (HIGH-3).
- **Docs:** `PRESENCE_COORDINATOR.md` and `COORDINATOR_ARCHITECTURE.md`
  addenda are clean and correctly position the substrate as BENEATH both
  tiers, NOT as a new tier or a room-tier deprecation. Reviewer A's
  hygiene cross-check should find no drift here. `AUDIT_occupancy_substrate_consumer_ripple.md`
  exists, lists the consumers the plan's D4 enumerated, but inaccurately
  claims FanRecheck is "Verified: yes" by the backcompat test (MEDIUM-1
  + HIGH-1 fix would resolve).

## Recommended fix-up sequence (before deploy)

1. **HIGH-3** (delete `or` substring fallback in lockstep test) — 1 LoC.
2. **HIGH-1** (rewrite `test_substrate_backcompat.py` to drive real
   `OccupancySubstrate` + real `_on_substrate_kind_changed`) — ~80 LoC.
3. **HIGH-2** (replace `test_room_substrate_integration.py` source-grep
   with a behavioral test) — ~60 LoC.
4. **MEDIUM-2** (cross-room dup entity_id WARN) — 6 LoC in
   `occupancy_substrate.py:225-234`.
5. **MEDIUM-1** (add `_zone_provenance_breakdown` row to the audit doc) —
   1 row.
6. **MEDIUM-4** (gate the room-tier `_trigger_rate_limited_refresh()` on
   the coordinator boot-settle flag) — ~5 LoC + audit doc update.

Defer LOW-1..LOW-4 to a follow-up hotfix unless the operator wants this
cycle's diff to land clean.

After fix-up, re-verify HIGH-1/2/3 by running the suite end-to-end with
the substrate stubbed to return wrong values for one path and confirming
the tests now FAIL (the current tests would not).

---

## Fix-up resolution (2026-06-05, commit 1de2ae1)

- **C-HIGH-1 — FIXED (partial, documented).** `test_substrate_backcompat.py`
  rewritten to drive a real `OccupancySubstrate` and assert dispatcher
  emit + provenance equivalence vs the pre-substrate direct path. The
  FanRecheck `STATE_OCCUPANCY_SOURCE` ring round-trip remains infeasible
  without a full HA coordinator fixture; the gap is documented in the
  module docstring (call-shape equivalence IS covered).
- **C-HIGH-2 — FIXED.** `test_room_substrate_integration.py` rewritten
  from source-grep to behavioral (mini-dispatcher routes real substrate
  edges into a production-mirroring handler); includes the B-C1 clobber
  regression guard.
- **C-HIGH-3 — FIXED.** Deleted the `or "update_room_occupancy(" in body`
  substring fallback in `test_v47181_sleep_wake_deadlock.py`.
- **C-MEDIUM-2 — FIXED.** Cross-room duplicate-entity WARN
  (`occupancy_substrate.py:231-247`, first claim wins).
- **C-MEDIUM-1 — FIXED.** `_zone_provenance_breakdown` row added to the
  D4 backcompat table; `_room_provenance` confirmed still populated
  (`presence.py:2448`).
- **C-MEDIUM-4 — DEFERRED.** Boot-settle gate on room-tier substrate
  refresh: `UniversalRoomCoordinator` has no `_boot_settle` flag; adding
  one exceeds the cheap-fix threshold and touches settle semantics.
  The v4.7.21 boot-storm settle gates already operate at the actuation
  layer, so this is hygiene, not correctness.
- LOW-1..4 deferred (cosmetic / dead-code removal; track as follow-up hotfix).
- Verified: 45 cycle tests pass; full suite no new regressions; compile clean.
