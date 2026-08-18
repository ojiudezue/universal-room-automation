# Guest / Census correctness — Review E (framing: lifecycle, boot ordering, restart, concurrency)

**Scope tip:** `1107d3b31` (feature/guest-census).
**Base:** `git merge-base develop feature/guest-census` = `3b373d3db7eb2d489645f2304d96fbd9da88b4f5`.
**Commits in range (7):** `eae92423c` → `7f7c15d20` → `36d92bc6e` → `44ccfabc6` → `c7c308a53` → `0e0ea97a2` → `1107d3b31`.
**Framing:** disjoint from A/B/C — I own runtime lifecycle (HA setup order, config-entry reload, RestoreEntity/state restoration, listener/timer cleanup, re-entrancy, tz).
**Prior reviews consulted:** `guest_census_plan_review.md`, `guest_census_review_{A,B,C}.md`.

## Verdict

**DO NOT SHIP.** One CRITICAL finding voids the entire r2 fix-up (both Part 1 live re-check AND the Transition-2 known-person branch that has been latent since v4.7.2). INV-GUEST-NO-RESIDENT is **not** satisfied by the shipped code on any production path — the invariant's mandatory falsifying repro (resident in a designated guest room across a restart) fires on my read, only delayed by the residual-clamp window.

The other findings are MEDIUM/LOW and cycle-close-able after the CRITICAL fix.

## Findings

### E-CRIT-1 — `_is_known_person_in_room()` reads the wrong bucket → always returns False in production

**Site:** `custom_components/universal_room_automation/domain_coordinators/presence.py:4803-4828` (helper, unchanged in this cycle — latent since v4.7.2 commit `d10ae7b26`).

**Consumers wired to it by THIS cycle:**
- `_discover_guest_rooms` boot-seed guard (`presence.py:4771`, added r1 `0e0ea97a2`).
- `_guest_room_gate_armed` Part-1 LIVE identity re-check (`presence.py:4943-4960`, added r2 `1107d3b31`).
- Also the pre-existing Transition-2 known-occupant branch (`presence.py:4781-4789`), broken since v4.7.2.

**Mechanism.** The helper does:

```python
manager = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
...
person_coord = manager.coordinators.get("person")
```

`CoordinatorManager._coordinators` is written **only** by `register_coordinator()` (grep of the repo: sole writers are `manager.py:376` and `manager.py:391`; every hit in `__init__.py` is presence/safety/security/mf/energy/hvac/optimization — see `__init__.py:2884, 2898, 2942, 3003, 3273, 3524, 3605`). `PersonTrackingCoordinator` is a `DataUpdateCoordinator`, **not** a `BaseCoordinator`, and is **never** registered — it is stored only under `hass.data[DOMAIN]["person_coordinator"]` (`__init__.py:2348`). Every other reader in `presence.py` uses that canonical bucket (`presence.py:2060, 3609, 3818, 4595, 5146, 5878, 6604`). This helper is the outlier — and always returns `None → False`.

**Falsifying repro (drives the plan's INV-GUEST-NO-RESIDENT reachability):**

1. Resident sitting still in a designated guest room; `binary_sensor.<room>_occupied.state = "on"` since hours ago.
2. HA restarts. `PersonTrackingCoordinator` is created (`__init__.py:2346`) and `first_refresh` awaited BEFORE `PresenceCoordinator.async_setup` runs → the object *exists* under `hass.data[DOMAIN]["person_coordinator"]`. It is NOT in `manager.coordinators`.
3. `_discover_guest_rooms` runs (`presence.py:2562`), computes `_is_known_person_in_room(room)` → False fallback (registry-lookup path never reached), seeds `first_seen = last_changed` clamped to `now − (threshold_s − 300)` = `now − 25 min` at defaults.
4. 300 s after restart, first `_run_inference` tick past the residual window. Part-1 live re-check calls `_is_known_person_in_room` → False fallback. Elapsed ≥ 30 min − 300 s = 25 min ≥ threshold. **Gate fires. GUEST arms on a resident.**

The r2 commit message asserts *"_is_known_person_in_room is a cheap in-memory dict lookup that reads fresh from hass.data"* — that description matches the **canonical** access pattern used elsewhere in this file, not the code actually shipped in the helper. The helper reads from a bucket nothing writes to.

**Why the test suite is green anyway.** `test_guest_census_correctness.py` monkeypatches the helper directly (`pc._is_known_person_in_room = lambda ...` at lines 653 and 887 in the branch tip). Review C's "per-site source mutation" of the helper's contents would still show the tests failing, but no test drives the real `coordinator_manager` bucket — this is the classic hollow-anchor pattern from `feedback_hollow_test_anchors`. Reviewer F is better placed to formalise that; I flag it here so the fix is not landed with test-only monkeypatch as its evidence base.

**Fix (small, safe, matches every sibling reader in this file):**

```python
def _is_known_person_in_room(self, room_name: str) -> bool:
    try:
        person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
        if person_coord is None:
            return False
        tracked = getattr(person_coord, "_tracked_persons", {}) or {}
        target = room_name.lower().replace(" ", "_")
        for _pid, person_data in tracked.items():
            location = (person_data or {}).get("location", "") or ""
            if location and location.lower().replace(" ", "_") == target:
                return True
    except Exception:
        _LOGGER.debug(
            "D5: could not check known persons in room '%s' (non-fatal)",
            room_name, exc_info=True,
        )
    return False
```

**Required after the fix, in this cycle:** at least one test that exercises the REAL helper against a fake `hass.data[DOMAIN]["person_coordinator"]` populated with `_tracked_persons` — no monkeypatch of the helper itself. And the mutation drill Reviewer C described must be re-run against the fixed helper, not the shim.

**Blast radius outside this cycle.** The Transition-2 branch (`presence.py:4781-4789`) has been dead since v4.7.2. Fixing E-CRIT-1 makes it live: a known resident toggling occupancy on a guest room WILL now cleanly disarm. Not a regression — this is the intended v4.7.2 semantics finally taking effect — but worth capturing in the README's "behavioral trades" section next to M1.

---

### E-MED-1 — 300 s residual-dwell floor is defensible in shape but has no measurement behind it; also cannot be evaluated for correctness until E-CRIT-1 is fixed

**Direct answer to the framing question:** *conditionally yes*, but the number's soundness cannot be judged from source; the plan documents no measurement and I have no recorder access from this review harness.

**Structural read.** The clamp guarantees `elapsed ≤ threshold − 300 s` at boot. If Part-1 works (E-CRIT-1 fixed), the 300 s window must cover the interval between `_discover_guest_rooms` returning and `person_coord._tracked_persons` acquiring a `location` for the resident room. Producers of `_tracked_persons.location`: BLE (Bermuda), device_tracker restored state, GPS. `person_coordinator.async_config_entry_first_refresh` is awaited at `__init__.py:2347` BEFORE presence init, which populates the dict skeleton, but `location` comes from downstream signals (BLE scanner re-discovery, geofence state-change events) that continue to arrive over seconds-to-minutes.

**Empirically, from repo signals only.** The repo's own `BOOT_SETTLE_MIN_INPUTS` machinery (v4.7.21) exists precisely because boot-time substrate settle is measured in tens of seconds to a couple of minutes. 300 s is comfortably above that in normal operation. It is **not** obviously enough if Bermuda BLE is degraded (scanner offline, iron-cage room) or if the resident's phone is not present but the resident is (e.g. left-phone case that the URA phone-left-behind machinery covers explicitly). In those regimes `location` may never arrive at all and the 300 s window merely delays the false-arm.

**Recommendation, non-blocking after E-CRIT-1:**

1. Land the clamp at 300 s as shipped.
2. Emit one INFO log line per boot per guest-designated room reporting `time_from_setup_to_first_location_seen` for each tracked person — one-shot, cheap, no new knob, satisfies `feedback_measure_before_build` retroactively.
3. If the observed interval on this deployment ever exceeds ~180 s, re-evaluate the constant (or add a boot-settle gate: skip Part-1's False-fallback firing while `person_coord.last_update_success_time < setup_time + BOOT_SETTLE_S`).

**Explicit no-verify claim:** I cannot measure BLE settle latency on the live house from this review harness. If a probe is run per §Measure-Before-You-Build, its result should be captured in the README pre-deploy note; without that data the 300 s constant is a plausible guess, not an evidenced choice. State this honestly in the release notes rather than asserting empirical sufficiency.

---

### E-MED-2 — `_discover_guest_rooms` re-runs only on full `async_setup`; a room newly flagged as guest via options-flow (no restart) is silently missed

**Sites:** call graph — only caller is `presence.py:2562` inside `async_setup`. The lifecycle handler `_on_room_entry_lifecycle` (`presence.py:3195`) refreshes the *substrate* subscriptions but does NOT re-run `_discover_guest_rooms`. Room ROOM entry `options_updated` therefore never rebuilds `_guest_room_state` / `_guest_room_unsubs` / `_guest_room_entity_to_name`.

**Consequence.** If the operator toggles `CONF_ROOM_IS_GUEST_ROOM` on an existing room via options flow, the change lands (options persisted), but presence does not register the sensor and D2 will not lead on it until the parent URA entry is reloaded — and per `feedback_parent_entry_reload_watchdog_hazard` that reload is itself hazardous. Under D2 the guest surface becomes fully room-driven, so a mis-registration here means guest mode is silently absent for that room. Symmetric on the un-flag path (state leaks in `_guest_room_state`).

**Recommendation.** Add a `SIGNAL_ROOM_ENTRY_LIFECYCLE` handler branch for `action == "options_updated"` that calls `_discover_guest_rooms()` — the function is already idempotent (clears state + unsubs at top, re-enumerates entries). Cheap (~3 LoC). Not a shipper if operator commits to always restarting after guest-flag changes, but should be documented explicitly if deferred.

---

### E-MED-3 — In-gate write of `first_seen` / `current_occupancy_known` (r2) is a read-write during a pure predicate; harmless today, but the invariant it relies on is easy to break

**Site:** `presence.py:4943-4960` (r2 addition inside `_guest_room_gate_armed`).

The r2 change makes what used to be a pure predicate a producer: it now writes `state_dict["first_seen"] = None` and `["current_occupancy_known"] = True` when the live identity check returns True. Docstring on the function still describes it as "evaluate whether any designated guest room triggers the sustained-occupancy gate" — no producer contract stated.

**Concurrency.** Two `_run_inference` tasks fired via `hass.async_create_task` in `_handle_guest_room_occupancy_change:4801` can execute back-to-back on the loop; the writes are dict item assignments with no `await` between them, so CPython atomicity means no torn state. But: the *listener* (Transition 1, `presence.py:4791-4798`) can interleave with the *gate*. Ordering:

- Listener fires Transition 1: writes `first_seen = now`, `current_occupancy_known = False`.
- Two ticks later, gate runs, live-check returns True (resident just placed by BLE), writes `first_seen = None`, `current_occupancy_known = True`.
- Another occupancy tick comes in with the room still "on"; listener re-fires, `_is_known_person_in_room` returns True → Transition 2 keeps `current_occupancy_known = True`.

No corruption, no false-GUEST. Worst case a benign ping-pong for one tick. **However** this bakes in the assumption that the gate is called strictly more often than adverse listener writes; if a future edit ever converts `_guest_room_gate_armed` to run inside a `for` loop that iterates multiple times per tick, or if `_run_inference` is ever parallelised more aggressively, the atomicity story frays.

**Recommendation, non-blocking:** either (a) rename/relocate the "clear stale state" side effect into a separate helper (`_reclassify_room_as_known(room_name)`) called from the gate — makes the producer role explicit — or (b) add a docstring line making the read-write contract explicit. Cheap either way. Not a shipper.

---

### E-LOW-1 — tz handling is correct; documenting so it doesn't recur as a phantom finding

`_discover_guest_rooms` uses `datetime.now(timezone.utc)` for the residual-clamp math; `_handle_guest_room_occupancy_change` and `_guest_room_gate_armed` use `dt_util.utcnow()`. HA's `dt_util.utcnow()` returns `datetime.utcnow().replace(tzinfo=UTC)` — tz-aware. `state.last_changed` is tz-aware UTC. Every subtraction (`now − first_seen`, `last_changed >= earliest_allowed`) is aware-vs-aware. No mismatch. The mixed choice is stylistic (two separate imports in the same file), not correctness — but LOW-1 for consistency: prefer `dt_util.utcnow()` throughout so any future test that stubs `dt_util.utcnow` for time control captures the boot-seed path too.

---

### E-LOW-2 — RestoreEntity is not in scope for `_guest_room_state` (RAM-only) and the r1 boot-seed correctly compensates via `state.last_changed`

No entity in the guest surface is a `RestoreEntity` — `_guest_room_state` lives on the coordinator and is RAM-only. The r1 boot-seed reads `binary_sensor.<room>_occupied.last_changed`, which the recorder repopulates via HA's own state restoration at core-restore time. `_discover_guest_rooms` runs from `PresenceCoordinator.async_setup`, which per the substrate/discovery ordering runs after core state has been repopulated in `hass.states`. This is fine; noting explicitly because "boot RestoreEntity poisoning" is a known bug class (#7-adjacent) and reviewers should not chase it here.

---

### E-LOW-3 — `raising=True` monkeypatch on `_cc_mod.dt_util` in the test fixture (line 79) is fine but couples the test to import layout

Non-issue for shipping; observation only. If a future refactor moves `dt_util` import inside functions, this fixture bricks — the failure is loud (raising=True), so acceptable.

---

## Restart-resilience summary (whole guest surface)

| State | Survives restart? | Correct? | Notes |
|---|---|---|---|
| `_guest_room_state[room].first_seen` | Boot-seeded from entity `last_changed` (r1) | **Only if E-CRIT-1 fixed** — otherwise seed always fires against residents after 25 min |
| `_guest_room_state[room].current_occupancy_known` | No (defaults False at re-seed) | Correct default; runtime intended to correct via Transition 2 / gate re-check — **both broken by E-CRIT-1** |
| `_guest_room_state[room].threshold_min` | Re-read from room merged options | OK |
| `_guest_room_entity_to_name` | Rebuilt from entity registry (D3) | OK; registry entry survives restart |
| `_guest_room_unsubs` | Rebuilt via fresh subscription | OK; cleared explicitly at top of `_discover_guest_rooms` — no listener leak |
| `_unidentified_first_seen` (Path A) | Not restored | Correct — Path A is census-driven, self-arms on first census tick |
| HouseState (GUEST) | Whatever the state machine restores | Correct — inference re-evaluates on first tick |

For **a genuine guest mid-visit**: boot-seed preserves their `first_seen`, gate re-checks identity (True → treated as guest correctly, Path B arms once threshold elapsed). Correct — **iff E-CRIT-1 fixed**.

For **a resident in a guest room**: gate re-check identifies them as known → Transition-2 clears first_seen. Correct — **iff E-CRIT-1 fixed**. Broken as shipped.

---

## Concurrency / re-entrancy summary

- `_run_inference` fires as `async_create_task`; two tasks can interleave. Reads/writes on `_guest_room_state` are dict item ops with no intervening awaits — CPython atomic, no torn state.
- Listener (`_handle_guest_room_occupancy_change`) and gate (`_guest_room_gate_armed`) can interleave; the r2 change adds a WRITE on what used to be a pure predicate (E-MED-3). Benign under current call topology, but the contract should be explicit.
- No new timers, no new subscriptions, no new coroutines — nothing to leak.

---

## Direct answer: is 300 s right?

**Structurally: defensible.** Larger than the URA repo's own boot-settle timings (v4.7.21 gates), small enough that the genuine-guest credit at default 30 min is 5/6 preserved. As a *safety margin against the false-GUEST class*, the value is in the right order of magnitude.

**Evidentially: unproven, and unprovable from source.** The plan asserts "empirically sufficient" but cites no measurement. No log-line captures `time_from_setup_to_first_location_seen` anywhere in the repo today. Per `feedback_measure_before_build`, this should have been probed before the constant was picked. Ship it, but add the one-line boot-timing log (E-MED-1 rec 2) and revisit if the observation exceeds ~180 s on this deployment.

**And most importantly:** the 300 s constant is only doing work if `_is_known_person_in_room` works. As shipped, it doesn't (E-CRIT-1). Fix that first; then 300 s is a reasonable, revisit-able floor.

---

## Ship checklist for this cycle to close

- [ ] Fix E-CRIT-1 (helper reads canonical bucket).
- [ ] Add one test that drives the REAL helper via a fake `hass.data[DOMAIN]["person_coordinator"]` (not `monkeypatch(pc._is_known_person_in_room, ...)`).
- [ ] Re-run Reviewer C's per-site mutation on the fixed helper.
- [ ] Add a boot-emitted INFO line per guest-designated room reporting `location` arrival latency (feeds future 300 s re-eval).
- [ ] Decide on E-MED-2 (options-flow re-discovery) — fix (~3 LoC) or document the "restart-required" operator contract.
- [ ] Confirm README pre-deploy note documents the 300 s as *plausible / unmeasured* until the boot-timing log lands.
