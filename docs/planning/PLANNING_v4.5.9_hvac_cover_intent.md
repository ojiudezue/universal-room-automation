# PLANNING v4.5.9 — HVAC cover dispatch tilt-awareness + intent-respecting cover management

**Status:** Plan complete, ready to implement
**Tier:** Tier 2 cycle (multiple deliverables, runtime behavior change for HVAC cover decisions, full review protocol + live validation)
**Predecessor:** v4.5.8

## Why

Two distinct issues both surface in `hvac_covers.py:CoverController` and benefit from a single coordinated fix:

1. **Dispatch bug (Bug Class #33 — third hit):** v4.5.0.4 made the per-room cover dispatcher tilt-aware. v4.5.6 made the per-room "already in target" gate helpers tilt-aware. Neither cycle threaded `CONF_COVER_TYPE` through `hvac_covers.py:_command_covers`. Result: when HVAC reopened covers at 18:00 CDT on 2026-05-09, Study A and Master Bedroom (both venetian) had their blinds raised to position=100 with slats stuck at tilt=0 — the pre-v4.5.0.4 venetian-as-roller symptom, just in a different code path. Live confirmed.

2. **Indiscriminate intent (user-flagged 2026-05-09):** the controller closes EVERY discovered cover when conditions converge, regardless of whether the room intends that cover to be open. It then reopens EVERY cover at 18:00, including ones HVAC didn't close and ones the room never intended to be open. The single `_covers_closed: bool` makes the open-after-solar bulk-fire indiscriminate.

These are independent fixes architecturally but touch the same dataclass + dispatch loop. Shipping them in one cycle:
- Avoids two restart cycles in 24 hours
- Lets us update tests once
- Forces a coordinated design (the closed-set design depends on dispatch landing the right service for tilt covers, otherwise the set tracks lies)

## Out of scope (deferred)

- **L2** — extending manual-override duration from 2hr to 24hr (needs design conversation)
- **L3** — forecast-aware skip when peak < 90°F (threshold tuning)
- **L4** — per-orientation classification (significant rework, v4.6.x candidate)
- **L5** — sleep-mode integration (edge case)
- **L6** — soft-gradient close via `set_position` (adds complexity, only works for shade not tilt)
- **L7** — heating-season inverse (winter solar gain capture; separate v4.6.x)
- **CONF_HVAC_COVER_ENTITIES tilt config** at CM level — three-tier auto-detection (see D1) covers the main case; explicit per-cover-type config can be added later if needed

## Deliverables

### D1 — Dispatch tilt-awareness (closes Bug Class #33 third hit)

**`hvac_covers.py:ManagedCover` dataclass gets a `cover_type: str = "shade"` field.**

**`discover_covers` resolves cover_type per-cover via three-tier strategy:**
1. **Room-derived** — for each cover that's referenced by a URA room entry, read the room's `CONF_COVER_TYPE`. If multiple rooms reference the same cover (rare but possible), prefer "tilt" if any room declares tilt.
2. **Feature-bitmask auto-detect** — for CM-level explicit covers (`CONF_HVAC_COVER_ENTITIES` not also in any room) OR rooms without `CONF_COVER_TYPE` set, read the entity's `supported_features` and check the tilt bits (`OPEN_TILT=128, CLOSE_TILT=256, SET_TILT_POSITION=64`). If any tilt bit is set AND `current_tilt_position` is exposed in attributes, treat as tilt. (Mirrors the verify-path tilt detection from v4.5.0.4.)
3. **Default** — "shade." Safe fallback that preserves pre-v4.5.9 behavior.

**`_command_covers` branches on cover_type:**
- `cover_type == "tilt"`: dispatch `cover.open_cover_tilt` / `cover.close_cover_tilt`
- `cover_type == "shade"`: dispatch `cover.open_cover` / `cover.close_cover` (unchanged)

**The "already in target state" check (lines 226-229 currently) becomes tilt-aware:**
- For tilt covers: check `current_tilt_position`. If close target and `tilt ≤ 5`, skip. If open target and `tilt ≥ 95`, skip. (Thresholds match v4.5.6 + verify path.)
- For shade covers: check `state.state` (unchanged).

#### Acceptance criteria
- **Verify:** Tomorrow's solar cycle — when HVAC closes for heat, Study A and Master Bedroom slats tilt to 0 (blind position stays at whatever the room's open mode set it to); blind position does NOT change to 0.
- **Verify:** When HVAC reopens at 18:00, Study A and Master Bedroom slats tilt back open (≥95).
- **Verify:** Living Room (shade) closes/opens via existing `cover.{open,close}_cover` — no behavior change.
- **Test:** Mirror tests for the dispatch matrix: (cover_type ∈ {shade, tilt}) × (action ∈ {open, close}) × (already-at-target vs not).
- **Test:** AST-grep on `_command_covers` to assert `current_tilt_position` is read in the tilt branch (Bug Class #33 prevention test).
- **Live:** Watch HVAC log on the next close — expect `HVAC Covers: close 1 covers` (or N) where N matches expected count, with the right service in HA logbook.

### D2 — Per-cover closed-set replaces single bool

**Replace `self._covers_closed: bool` with `self._hvac_closed: set[str]`** of entity IDs that HVAC explicitly closed in the current solar window.

**Close-for-heat loop:**
```python
if should_close:
    for entity_id, cover in self._covers.items():
        # gates: intent (D3), occupancy (D5), opt-out (D4), already-closed (D1)
        if not self._should_hvac_close(entity_id, cover, now):
            continue
        await self._command_close_one(entity_id, cover, now)
        self._hvac_closed.add(entity_id)
```

**Open-after-solar loop:**
```python
if not in_solar_window and self._hvac_closed:
    for entity_id in list(self._hvac_closed):
        cover = self._covers.get(entity_id)
        if cover is None:
            self._hvac_closed.discard(entity_id)
            continue
        # If user manually re-opened during the closed window, drop from set
        if cover.manual_override_until:
            override_end = datetime.fromisoformat(cover.manual_override_until)
            if now < override_end:
                self._hvac_closed.discard(entity_id)
                continue
        await self._command_open_one(entity_id, cover, now)
    self._hvac_closed.clear()
```

#### Acceptance criteria
- **Verify:** Tomorrow's cycle — only covers HVAC closed at ~13:00 get reopened at 18:00. Manually-closed covers stay closed.
- **Test:** Set up mocks where 5 covers are discovered, 2 are intended-open, HVAC closes only those 2, then opens only those 2 at end-of-window. The 3 untouched covers stay untouched.
- **Test:** Manual override during HVAC's closed window → cover gets dropped from `_hvac_closed`, not reopened.
- **Test:** Cover removed from discovery (config change mid-day) → handler tolerates `cover is None`, drops silently.

### D3 — Intent-respecting close/open via per-room predicate

**New helper on `RoomAutomation` class (in `automation.py`): `is_cover_currently_intended_open(now: datetime) -> bool`.**

Returns whether the room's cover-mode policy says this cover should be open at this moment:

| `CONF_COVER_OPEN_MODE` | Returns |
|---|---|
| `none` | `False` always — manual-only, never HVAC-managed by intent |
| `on_entry` | `False` (open is occupancy-driven, not time-driven; HVAC doesn't know future occupancy) |
| `at_time` | `True` if `_is_cover_open_time(now) AND not _is_cover_close_time(now)` |
| `on_entry_after_time` | `True` if `_is_cover_open_time(now) AND not _is_cover_close_time(now)` (treats time-window-eligible as intent-open) |
| `at_time_or_on_entry` | `True` if `_is_cover_open_time(now) AND not _is_cover_close_time(now)` |

**`CoverController._should_hvac_close` consults this predicate** for every cover that maps to a room. Covers without a mapped room (CM-level explicit) default to "intended open" so HVAC's solar-gain logic still applies.

#### Acceptance criteria
- **Verify:** A room with `cover_open_mode = none` does not have HVAC issue close on its covers, even on a hot solar afternoon.
- **Verify:** A room with `cover_open_mode = at_time` and `cover_open_hour = 7` and `cover_close_hour = 20`: HVAC's 13:00 close fires (`_is_cover_open_time=True, _is_cover_close_time=False` → intent=open), HVAC's 18:00 open also fires.
- **Verify:** Same room at 21:00 (after close hour): intent=closed, HVAC wouldn't close (already past close anyway), HVAC's reopen attempt at 18:00 was already valid because 18 < 20.
- **Test:** All 5 mode values × time-window edge cases (before-open, mid-window, after-close).

### D4 — Explicit `CONF_COVER_HVAC_MANAGED` opt-out

**New per-room CONF, default `True`.** Room-level toggle to exempt the room's covers from HVAC management entirely.

- Defined in `const.py`
- Form field added to the `cover_behavior` step in `config_flow.py` (both setup and reconfig flows)
- Read by `CoverController.discover_covers` — covers from rooms with `CONF_COVER_HVAC_MANAGED = False` are excluded from `self._covers`. They're still managed by per-room automation; HVAC just doesn't touch them.
- Strings + translations updated

This is the explicit-intent escape hatch. Use case: master bedroom where someone naps, sensory bedroom for a kid, library with light-sensitive art.

#### Acceptance criteria
- **Verify:** Setting `cover_hvac_managed = False` on a room and waiting for next solar cycle → HVAC log shows the room's covers excluded from discovery; covers untouched even on hot solar afternoon.
- **Test:** AST-grep that `CONF_COVER_HVAC_MANAGED` is read in `discover_covers` (Bug Class #32 prevention).
- **Test:** Cover discovery excludes covers from rooms where `CONF_COVER_HVAC_MANAGED = False`.

### D5 — Occupancy-aware skip (L1)

**`CoverController._should_hvac_close` skips covers in currently-occupied rooms unless the room is meaningfully above its cooling setpoint.**

- Read room state from coordinator's `coord.data.get(STATE_OCCUPIED, False)`
- Read room temp from `coord.data.get(STATE_TEMPERATURE)`
- Read effective cooling setpoint via the HVAC zone the room belongs to (`zone.target_temp_high`)
- "Meaningfully above" threshold: configurable, default `OCCUPIED_CLOSE_TEMP_DELTA = 2.0°F`
- If occupied AND temp < setpoint + 2°F: skip (don't close, leave it open for the user)
- If occupied AND temp ≥ setpoint + 2°F: close (the user is uncomfortable, banking helps them too)
- If vacant: close per other rules

#### Acceptance criteria
- **Verify:** A user reading in the Living Room with all rooms occupied — Living Room temp 74°F, setpoint 72°F (delta = 2°F = right at threshold). HVAC skips close per "not meaningfully above."
- **Verify:** Same room, temp 76°F (delta = 4°F): HVAC closes despite occupancy.
- **Test:** Mock zone + room states across the matrix (occupied/vacant) × (cool, warm, hot).

### D6 — Diagnostic surfacing

**`hvac.py:1467-1470` already exposes `solar_banking_zones` on the HVAC mode sensor.** Add:

- `hvac_closed_set` attribute: list of cover entity IDs currently held closed by HVAC (the `_hvac_closed` set, sorted).
- `hvac_closed_count` attribute: integer count.

So the user can see "what HVAC has closed" at a glance from the diagnostic sensor.

#### Acceptance criteria
- **Verify:** During a solar close window, `sensor.ura_hvac_coordinator_*` (the mode sensor) has `hvac_closed_set` listing the actual closed covers.
- **Test:** Unit test that the sensor's `extra_state_attributes` returns the `_hvac_closed` set as a sorted list.

### D7 — Tests + Quality docs

**Mirror-style test file: `quality/tests/test_v459_hvac_cover_intent.py`** with 4 sections:
- D1 dispatch-tilt-awareness (12-15 tests across the cover_type matrix)
- D2 closed-set lifecycle (4-6 tests including manual-override interaction)
- D3 intent predicate (8-10 tests across the cover_open_mode × time-window matrix)
- D4-D5 opt-out + occupancy skip (6-8 tests across the gating matrix)
- D6 diagnostic surfacing (2-3 tests)
- Source contract tests (4-5 tests asserting key invariants in source)

**Update `docs/QUALITY_CONTEXT.md`:**
- Add note under Bug Class #33 ("Sibling Helpers Skipped") that the v4.5.9 cycle closed the third hit (HVAC dispatch path).
- Possibly add Bug Class #34 if a new pattern emerges. Initial guess: "**Indiscriminate Bulk Action Without Per-Item Intent Check**" — applies when a controller treats a discovered set as homogeneous and issues bulk actions when each item has its own per-item intent. The fix is per-item gating + tracked state. URA hits: `hvac_covers.py` pre-v4.5.9 (single bool, bulk fire). Worth thinking about whether this generalizes elsewhere (energy_circuits, energy_pool?) before declaring it a class.

#### Acceptance criteria
- **Verify:** All v4.5.9 tests pass; isolation check 0 failures.
- **Verify:** QUALITY_CONTEXT.md updated.

## Tier 2 Review Plan

### Pre-review baseline
```bash
git tag pre-review-v4.5.9 -m "Pre-review baseline for v4.5.9"
```

### Review 1 (Core A — domain logic)
- D1 dispatch tilt-awareness: walk through every code path, confirm tilt branch reachable for each cover_type resolution tier
- D2 closed-set: verify lifecycle correctness — set populated on close, cleared on open, dropped on manual-override
- D3 intent predicate: each `cover_open_mode` value mapped correctly; edge cases (open_hour > close_hour wrapping past midnight) considered
- Bug class checklist (QUALITY_CONTEXT.md):
  - #1 Stale data source: room data read at decision time, not stale snapshot
  - #4 Domain mixing: lights vs switches still split; tilt vs shade explicitly branched
  - #11 Async forgetting: all `await`s present
  - #28 Untracked input fields: every CONF read at runtime
  - #32 Form field with no runtime reader: `CONF_COVER_HVAC_MANAGED` reader exists
  - #33 Partial fix: ALL cover dispatch paths in repo (per-room + HVAC) consistent

### Review 2 (Core B — race conditions, restart, lifecycle)
- HVAC restart during solar window: `_hvac_closed` is in-memory; on restart, set is empty; controller re-evaluates conditions, re-closes covers if conditions still met. Acceptable (one extra close call, idempotent).
- Race: room manually opens cover at 13:30 (within manual_override_window). HVAC's 13:35 tick sees override_until > now, skips. ✓
- Race: room's automation fires close at 13:00 just before HVAC's 13:00 close. Both fire. Per-room close + HVAC close both target same entity. Idempotent. ✓
- Lifecycle: cover removed from URA configuration mid-day. Discovery hasn't re-run; `self._covers[id]` still present; eventually re-discovered and dropped. Could leave stale entry in `_hvac_closed` if cover was closed pre-removal. Defensive: drop entries from `_hvac_closed` whose entity_id is no longer in `self._covers` at open-time.
- Cross-coordinator: zone preset change to "away" mid-window does NOT affect HVAC cover decisions; covers are independent of preset.

### Live validation (Review 3, post-deploy)
- Wait for next solar window (likely 13:00 CDT next clear day)
- Watch HVAC log: expect "HVAC Covers: close N covers" where N is the count of intended-open + occupied-comfort + non-opt-out covers
- Watch the affected covers' tilt/position transitions: tilt covers should tilt-close, shade covers should position-close
- Watch `sensor.ura_hvac_coordinator_*` `hvac_closed_set` attribute: should match the actual closed covers
- After 18:00 (window end): expect the same N covers to reopen with cover_type-correct service
- Verify untouched covers stayed untouched throughout

## Cost

| Component | Effort | LoC |
|---|---|---|
| D1 dispatch tilt-awareness | 1 hour | ~50 |
| D2 closed-set | 30 min | ~30 |
| D3 intent predicate | 1 hour | ~40 |
| D4 opt-out CONF + form | 30 min | ~25 + strings |
| D5 occupancy-aware skip | 30 min | ~20 |
| D6 diagnostic surfacing | 15 min | ~10 |
| D7 tests | 2 hours | ~350 (test file) |
| Docs (QUALITY_CONTEXT, README) | 30 min | ~80 |
| **Total** | **~6 hours** | **~600 LoC** (mostly tests) |

## Risks ranked

1. **Three-tier cover_type resolution might mis-detect on edge cases.** A cover with tilt bits in `supported_features` but no actual tilt support (some integration weirdness) could get misclassified as tilt and the dispatcher would call a service that no-ops. Mitigation: the verify path (line 226-229) detects no-op; the closed-set won't track it; manual fallback. Low blast radius.

2. **`is_cover_currently_intended_open` predicate accuracy depends on `cover_open_mode` correctness.** If a user has `cover_open_mode = on_entry` (HVAC will return `False` always per design — HVAC can't know future occupancy), HVAC will skip closing those covers. That's correct per intent but means rooms with `on_entry`-only mode get NO solar-gain protection. Acceptable; user can change to `at_time_or_on_entry` if they want HVAC to manage.

3. **`_hvac_closed` set lifecycle on HA restart mid-window:** in-memory state is lost. On restart inside solar window, controller re-evaluates from scratch — intent predicate says "intended open" → re-closes (idempotent for already-closed covers). On restart AFTER window end with stale closed state on covers: the open-after-solar branch never runs (window already past) — covers stay closed until next per-room timed_open. Manageable; documented in restart-resilience review.

4. **CONF_COVER_HVAC_MANAGED form field**: easy to add; the bigger risk is that a user toggling it mid-day doesn't take effect until the next coordinator update or reload. Acceptable.

## Acceptance criteria summary

The release is "done" when:
- All v4.5.9 tests pass, isolation check 0 failures, no regressions in v4.5.0-v4.5.8 tests
- Tier 2 review docs in `docs/reviews/code-review/v4.5.9_*.md` (one for Review 1, one for Review 2)
- Source-contract tests assert: tilt branch in `_command_covers`; closed-set is a set not a bool; intent predicate exists in `RoomAutomation`; `CONF_COVER_HVAC_MANAGED` is read in `discover_covers`; `hvac_closed_set` is in mode sensor attributes
- Live validation post-deploy confirms the matrix on the next solar cycle
- README_v4.5.9.md describes WHAT changed; vibememo entry 009 captures WHY (decision trail for the indiscriminate-bulk-action redesign)

## Memory updates

After deploy + live validation:
- Update `feedback_no_fabrication.md` if anything new about the `supported_features` bitmask check turned up
- Add a new memory `feedback_intent_respecting_controllers.md`: when a controller manages a discovered set of items, prefer per-item intent gating + tracked state over bulk actions
