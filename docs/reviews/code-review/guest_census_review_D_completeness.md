# Guest / Census correctness — Tier-2-DB Review D (adversarial completeness)

- **Cycle:** `CENSUS-GHOST-DEDUP-1` (plan rev-2, `docs/planning/PLANNING_guest_census_correctness.md`).
- **Branch reviewed:** `feature/guest-census` @ **`1107d3b31`** ("GUEST-CENSUS HIGH fix-up: boot false-GUEST closure").
- **Diff base (verified):** `git merge-base develop feature/guest-census` = `3b373d3db7eb2d489645f2304d96fbd9da88b4f5`. `git log 3b373d..1107d3 --oneline | wc -l` = **7** commits (matches the seven cycle commits listed in the planning doc's revision history). Prior reviewer's silent-drop of `eae92423c` (the D1 commit) not repeated.
- **Framing:** D — adversarial completeness. Sole job: **falsify INV-GUEST-NO-RESIDENT** (2026-08-16, plan §Falsifiable invariants). Diff-blind and pre-existing-code-inclusive per Tier-3 method — the same discipline the plan requires even at Tier-2-DB, because this fix-up round targets exactly the failure mode a "SHIP" convergence missed once already.

---

## Verdict: **DO-NOT-SHIP.**

**INV-GUEST-NO-RESIDENT is falsified in the shipped code by a concrete, legal, reachable production path.** The Part-1 "live re-check" that the fix-up commit claims closes the boot hole is **dead code in production** because it reads an attribute that no one writes. The Part-2 300 s residual clamp then leaves a **5-minute window** after each restart in which a resident in a designated guest room causes GUEST to arm — exactly the operator repro the fix-up was written to eliminate. The `test_gate_reverify_identity_at_gate_time` regression test PASSES only because it monkeypatches the very method whose production body is broken. This is the "hollow test anchor" pattern (`feedback_hollow_test_anchors.md`) applied to the load-bearing site.

Ranked: **1 CRITICAL, 1 HIGH, 2 MEDIUM, 2 LOW.** Fix the CRITICAL + HIGH, re-verify with a test whose oracle drives the production path, then re-run D's enumeration. Do not deploy on the current tip.

---

## Independent enumeration of the arming surface

Built by grep, then diffed against the plan's / fix-up's implicit list. Every path that can flip `_guest_room_gate_armed(...)` to True:

**Writers of `_guest_room_state[room]["first_seen"]` (must not be pre-aged w/ a resident present):**

1. `presence.py:4793` — Transition 1 in `_handle_guest_room_occupancy_change`. Sets `first_seen = now` when occupancy toggles ON and `_is_known_person_in_room(room_name)` returns False.
2. `presence.py:4802` (post fix-up @ old range `:4772-…4805` on the branch tip) — **boot seed** in `_discover_guest_rooms`: `first_seen = max(last_changed, now - threshold_s + GUEST_BOOT_SEED_MIN_RESIDUAL_S)` when the entity is currently `on` and `_is_known_person_in_room` returns False.

**Writers of `current_occupancy_known` (must not be stuck-False when a resident is actually there):**

- `presence.py:4785` — Transition 2 (`True`) when the listener sees `on` AND `_is_known_person_in_room` returns True.
- `presence.py:4798` — Transition 1 (`False`) when the listener sees `on` AND `_is_known_person_in_room` returns False.
- `presence.py:4778` — Transition 3 (`False`) when the listener sees `off`.
- `presence.py:4712` — `_discover_guest_rooms` init (`False`).
- `presence.py:4957-4958` — **NEW fix-up Part-1** live re-check inside `_guest_room_gate_armed`: sets `current_occupancy_known=True` and clears `first_seen` when `_is_known_person_in_room` returns True.

**Every "known-person" verdict routes through ONE oracle:** `PresenceCoordinator._is_known_person_in_room` (`presence.py:4803-4828`), which reads `getattr(person_coord, "_tracked_persons", {})` at line 4818.

**Callers of `_guest_room_gate_armed` (True → arms GUEST under D2):** `presence.py:5391` (home-like branch) and `:5399` (inside-GUEST re-eval). Both routes are load-bearing under D2's `guest_armed = guest_room_gate_armed` composition.

---

## Findings

### D-CRIT-1 — `_is_known_person_in_room` reads a non-existent attribute; the entire identity oracle is dead code. INV-GUEST-NO-RESIDENT falsified.

**Site:** `custom_components/universal_room_automation/domain_coordinators/presence.py:4818`
```python
tracked = getattr(person_coord, "_tracked_persons", {})
for _pid, person_data in tracked.items():
    location = person_data.get("location", "")
    if location and location.lower().replace(" ", "_") == room_name.lower().replace(" ", "_"):
        return True
```

**Evidence (grep, whole repo, production sources only):**
```
$ git grep -n "_tracked_persons\b" -- '*.py' \
    | grep -v "_tracked_persons_count\|_tracked_persons_away\|tests/"
custom_components/.../presence.py:1574:   # (comment, referring to all_tracked_persons_away)
custom_components/.../presence.py:4818:   tracked = getattr(person_coord, "_tracked_persons", {})
```
There are **zero writers, zero attribute definitions, zero assignments** to `_tracked_persons` anywhere in the URA package. `PersonCoordinator` stores its per-person state in `self.data` (a `DataUpdateCoordinator.data` dict keyed by `person_name`) — see `person_coordinator.py:273`, `:419`, `:452-455`, `:528-531`, `:1420-1434`. `PersonCoordinator.tracked_persons` (no leading underscore) exists at `:104` but is a plain LIST of configured person names, not a mapping with per-person `location`.

The reader in `_is_known_person_in_room` therefore evaluates `getattr(..., "_tracked_persons", {})` → `{}` (the default), iterates an empty dict, and always falls through to `return False` at `:4828`. This is a permanent False fallback in production.

**Consequence in production (every downstream site that consumes this oracle):**

- **`_discover_guest_rooms` boot seed (`:4776`)**: `_is_known_person_in_room` is False → seed always plants for any `on` room, regardless of who's in it.
- **`_handle_guest_room_occupancy_change` Transition 1/2 branch (`:4781`)**: Transition 2 (known → disarm) is unreachable; every occupied→ON transition arms Transition 1 (`first_seen = now`), including a resident walking into the room.
- **NEW fix-up Part-1 in `_guest_room_gate_armed` (`:4941`)**: the "consumer verifies producer" live re-check evaluates False for every room every tick. The stated defence — "clear `first_seen` and set `current_occupancy_known=True` when a known person is present" — never fires in production.

**Concrete falsifying repro (INV-GUEST-NO-RESIDENT):**

- **Config:** any URA room with `CONF_ROOM_IS_GUEST_ROOM=True` and `CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN=30` (the live default on all three flagged rooms per plan §D2 M1). Take `Downstairs Guest Bedroom` for concreteness.
- **Pre-restart state:** one resident asleep in that bed for the last 3 hours. `binary_sensor.downstairs_guest_bedroom_occupied.state == "on"`, `last_changed == now − 3 h`.
- **Action:** HA restart (planned or unplanned).
- **Boot t=0:** `_discover_guest_rooms` runs. `_is_known_person_in_room("Downstairs Guest Bedroom")` → `getattr(pc, "_tracked_persons", {})` → `{}` → returns `False`. Part-2 clamp fires:
  ```
  earliest_allowed = now_utc − (1800 − 300) s   = now − 25 min
  last_changed (= now − 3 h) < earliest_allowed  → seed = earliest_allowed
  ```
  `first_seen = now − 25 min`, `current_occupancy_known = False`, `threshold_min = 30`.
- **Boot t = +5 min:** any inference tick (`census_update`, `state_change`, etc.) hits `_guest_room_gate_armed(now)`. `first_seen` non-None ✓. `current_occupancy_known` is False ✓. Part-1 live re-check calls `_is_known_person_in_room("Downstairs Guest Bedroom")` again → still returns False (still empty `_tracked_persons`). `elapsed_min = (now − first_seen) / 60 = 30.0`. `elapsed_min >= threshold_min` → **`return True`**.
- **Composition (D2):** `guest_armed = guest_room_gate_armed = True` at `presence.py:5391`. GUEST inference proceeds.

**Result:** exactly 5 minutes after every HA restart, if a resident happens to be in *any* designated guest room, GUEST arms. INV-GUEST-NO-RESIDENT falsified. This is *the same failure mode* the fix-up commit's message describes as "the boot false-GUEST hole" — the fix does not close it, because the fix's active ingredient does not exist in production.

Note: this is a **legal reachable state**, not a hypothetical. Guest bedrooms *are used by residents* — that is the entire premise of the operator repro. `Downstairs Guest Bedroom` sleeping a resident is a normal Sunday night. A restart during an overnight is a normal Home Assistant week.

**Test authority (why the suite didn't catch it):** `test_gate_reverify_identity_at_gate_time` in `quality/tests/test_guest_census_correctness.py:918-981` uses helper `_seed_bare_pc_with_guest_room` (`:851-915`), which at line **887** does:
```python
pc._is_known_person_in_room = lambda rn, _f=identity_flag: _f["known"]
```
The test's "known-person" oracle is a lambda over a synthetic dict, not the production method. Flipping `identity_flag["known"] = True` (test line 961) drives the code path *around* the actual `_tracked_persons` bug. The fix-up commit's own drill "FIX-M1 (neuter Part-1 live re-check) → test FAILS" therefore proves only that **the Part-1 branch is reachable when its oracle is stubbed**; it proves nothing about the production oracle. This is the "hollow test anchor" pattern (`feedback_hollow_test_anchors.md`, `feedback_falsify_before_asserting.md`) at the load-bearing site.

**Fix requirement (minimum bar to satisfy INV-GUEST-NO-RESIDENT):**

1. Rewrite `_is_known_person_in_room` to read the attribute PersonCoordinator actually populates — `person_coord.data` — using the same lookup shape `person_coordinator.get_location(...)` uses (`person_coordinator.py:1420-1422`). Verify against a live HA snapshot that `data` is non-empty within a few seconds of boot.
2. Handle the "known but not yet placed" boot window: at least one of `person_coord.data` populated, `data[name]["location"]` non-`"unknown"` and non-`"stale"`, and `last_updated` fresh. A resident whose Bermuda area sensor has not resolved yet is *not* "known-away"; treat as unknown-identity for arming purposes only after a bounded boot-settle window that is longer than person_coordinator's first refresh.
3. Add a test whose oracle IS the production `_is_known_person_in_room` (not a monkeypatched lambda) and whose fixture places a real `PersonCoordinator`-shaped dict at `hass.data[DOMAIN]["coordinator_manager"].coordinators["person"].data`. Then re-run the boot false-GUEST repro end-to-end. That test on the current tip must FAIL to prove the bug; after fix, must PASS.
4. Consider whether Part-2's 300 s residual clamp is even the right ceiling once (1) is fixed — see D-MED-2.

---

### D-HIGH-1 — Same dead oracle makes the runtime Transition-1 path arm GUEST for residents entering a flagged guest room. (Pre-existing; converted from latent to lethal by D2.)

**Site:** `presence.py:4781` inside `_handle_guest_room_occupancy_change`:
```python
occupant_known = self._is_known_person_in_room(room_name)
```

This bug **predates the cycle** (the method has always used this oracle) but was benign under the old OR composition, because Path A generally arm-races Path B's 30-min timer for common false-positive shapes. D2 makes Path B the SOLE arming source (plan §D2), which converts every event-driven false-negative in `_is_known_person_in_room` into a live GUEST arming.

**Concrete repro (no restart required):**

- **Config:** `Downstairs Guest Bedroom`, `is_guest_room=True`, `threshold=30 min`.
- **State:** room unoccupied at t=0. Resident (Oji) walks in at t=0 and stays for 30+ min (afternoon nap; working from that room; putting away laundry and then reading; etc.).
- **t=0:** `binary_sensor.downstairs_guest_bedroom_occupied` transitions off→on. Listener fires. `_is_known_person_in_room("Downstairs Guest Bedroom")` → `False` (dead code). Transition 1: `first_seen = now`, `current_occupancy_known = False`.
- **t = +30 min:** any inference tick. Gate check. Part-1 live re-check still returns False (dead code). `elapsed >= threshold` → `return True`. GUEST arms with a resident in the bedroom.

This is precisely the *daytime-guest false-positive class* the plan says D2 is meant to *reduce*, re-created inside a flagged guest room by the D2 composition's reliance on an oracle that never says "known". Under the old OR, Path A's census signal was often decisive within Path A's 5-min timer; under D2 there is no other channel.

**Fix:** subsumed by the D-CRIT-1 rewrite of `_is_known_person_in_room` (this consumer, and the boot seed, and Part-1's re-check all recover once the oracle actually works). **But**: even after that rewrite, the arm-race persists for the first N seconds a resident is in the room BEFORE Bermuda resolves them into the area. Reviewer strongly recommends: on Transition 1 (arm), do a **deferred re-check at threshold** that consults the oracle again before firing (i.e. keep Part-1's live re-check pattern in `_guest_room_gate_armed` — it is architecturally correct; it just needs a working oracle). Do not rely on the state-change listener as the sole opportunity to reclassify.

---

### D-MED-1 — `_is_known_person_in_room` uses a fragile `slug == slug` match between `person.data["location"]` and URA `CONF_ROOM_NAME`. Silent mismatch reproducible today for at least one live room.

**Site:** `presence.py:4821`:
```python
if location and location.lower().replace(" ", "_") == room_name.lower().replace(" ", "_"):
```

`person_coordinator.py:467` shows `location` (aka `resolved_room`) is derived from a **Bermuda area sensor** on each tracked person — i.e. it carries the HA **area registry name**, not URA's `CONF_ROOM_NAME`. These two vocabularies coincide for most rooms but are not guaranteed identical:

- **Upstairs Guestroom** (URA `CONF_ROOM_NAME`) is exactly the room D3 exists for: its HA area was renamed to something like `Upstairs Guest Bedroom`. After D3 wires the correct `binary_sensor.upstairs_guest_bedroom_occupied` into the guest-room listener, a resident in that room will produce a Bermuda location of `"Upstairs Guest Bedroom"`, which slug-compares to `upstairs_guest_bedroom` — **not** equal to `upstairs_guestroom` (the slug of the URA room_name). `_is_known_person_in_room("Upstairs Guestroom")` returns False even for a fully-resolved, fully-tracked resident. Same false-GUEST class as D-CRIT-1, but not fixed by simply switching the reader to `person_coord.data`.
- Any room whose HA area name has ever been edited independently of URA's `CONF_ROOM_NAME` has the same latent gap.

**Reachability:** the exact rename gap D3 fixes at the entity_id level is still present at the location-string level.

**Fix:** resolve URA room ↔ HA area via the same entity-registry-based reverse map D3 already builds (`_guest_room_entity_to_name` → `entity.area_id` → `area_registry.async_get(area_id).name`), and compare AREA against `person_data["location"]`. Or, more robustly, cache the room's `area_id` at discovery time and compare person's Bermuda `area_id` if that is what Bermuda actually stores. This is a small extension of the D3 machinery; do not rely on string equality between two independently-editable name spaces.

---

### D-MED-2 — Kill-switch off→on re-arms from a stale boot seed. Legal repro.

**Sites:** `_guest_room_gate_armed` kill-switch handling `presence.py:4842-4844`; `_discover_guest_rooms` seed at `:4776` runs at boot and on reconfigure. `_clear_guest_room_first_seen` clears `first_seen` only when the gate is called with detection OFF.

**Repro:**
1. Operator disables `switch.ura_presence_guest_detection_enabled` before an HA restart.
2. Resident asleep in a flagged guest room across restart.
3. Boot: `_discover_guest_rooms` runs regardless of the switch (there is no switch guard in the discovery path). Seed plants `first_seen = now − 25 min` per Part-2 clamp. `_guest_room_gate_armed` is called by the first inference tick with detection still OFF → `_clear_guest_room_first_seen()` runs, clearing the stale seed. Safe *only if* an inference tick actually runs while detection is still OFF.
4. **Race variant:** if the operator flips the switch on within `< SCAN_INTERVAL_CENSUS` of boot (or before the first inference tick following boot for any other reason), the gate's very first call may see detection True. Then the arithmetic is identical to D-CRIT-1: seed 25 min old, live re-check dead, fires at t=+5 min.

**Fix:** either (a) also clear stale `first_seen` on the OFF→ON edge of the kill-switch (mirror the discovery-time seed contract), or (b) gate `_discover_guest_rooms`'s boot seed on the switch state and re-run seed on OFF→ON. Cheap; belt-and-braces.

*(D-MED-2 becomes moot once D-CRIT-1 is properly fixed. Keep the fix anyway — kill switches are load-bearing safety, and the current asymmetry is a foot-gun.)*

---

### D-LOW-1 — Fixed-slice grep windows still guarding some sites. Silent-decay risk.

**Site:** `quality/tests/test_v472_feature_b_guest_signal.py` — the fix-up bumped `_discover_guest_rooms` window `6000→8000` and `_guest_room_gate_armed` `1500→3000`. This pattern locates a call site by slicing a fixed character window out of the source string; as the guarded method grows past the window, the assertion silently checks a substring of the wrong region. The file already has a `_method_body(..., span=N)` helper (see `test_guest_census_correctness.py:381`) — convert the remaining fixed-slice anchors to that helper so a method rename or growth cannot silently defeat the guard.

**Assessment of whether any already guard nothing:** the current bump was reactive (the fix-up outgrew the old windows and the tests started failing loudly). No evidence that either currently guards a slice with no landmark inside. Non-blocking; recommend as part of the D-CRIT-1 test-authority fix pass.

---

### D-LOW-2 — Mixed `datetime.now(timezone.utc)` vs `dt_util.utcnow()` in the same file.

**Site:** Part-2 clamp uses `datetime.now(timezone.utc)`; the rest of `_handle_guest_room_occupancy_change` and `_guest_room_gate_armed` use `dt_util.utcnow()`. Both are tz-aware UTC and comparable, so no naive/aware TypeError today. Style-only; recommend harmonising to `dt_util.utcnow()` (matches the rest of the coordinator and is what the QUALITY doc's Bug Class #11 fix pattern expects). Non-blocking.

---

## Does INV-GUEST-NO-RESIDENT hold across the whole surface?

**No.** Falsified by D-CRIT-1 (boot path, 5-min post-restart window, any resident in any flagged guest room) and D-HIGH-1 (steady-state path, any resident going into a flagged guest room for 30+ min). D-MED-1 additionally falsifies it for Upstairs Guestroom even after the D-CRIT-1 fix, until the room-name vs area-name coupling is repaired.

INV-GUEST-LEAD (the older, weaker invariant) does hold, in the sense that only Path B arms GUEST. The plan's own note that INV-GUEST-LEAD "did no work" applies with equal force to any invariant a dead-code fix can satisfy — INV-GUEST-NO-RESIDENT was written precisely because INV-GUEST-LEAD was too weak; that upgrade is meaningful only if the reviewers driving to it use test oracles that are not themselves stubs of the production oracle.

## Required actions before ship

1. Fix D-CRIT-1: rewrite `_is_known_person_in_room` to read `person_coord.data` (the real store) and to handle the boot-window "known but not yet located" case. Add a test whose oracle is production, whose fixture builds a real `PersonCoordinator.data`-shaped dict, and whose repro is the operator scenario end-to-end. Test must FAIL on the current tip; must PASS after fix.
2. Fix D-HIGH-1 as a side-effect of (1), plus a deferred-re-check-at-threshold in `_handle_guest_room_occupancy_change` OR keep the Part-1 gate re-check pattern (architecturally correct once the oracle works) as the single re-verification point.
3. Fix D-MED-1: match on HA `area_id` (or area name resolved from the same entity registry D3 uses), not on `slug(CONF_ROOM_NAME)`.
4. Fix D-MED-2: symmetric first_seen clear on the kill-switch OFF→ON edge (or gate the discovery-time seed on the switch state).
5. Re-run D's completeness enumeration after the fix: any new writer of `first_seen`, any new consumer of the identity oracle, and any new discovery/reload code path.
6. Address D-LOW-1 as part of the test-authority pass (convert to `_method_body`).

Only then re-dispatch reviews A/B/C on the fix-up-of-the-fix-up, and re-run D once more.
