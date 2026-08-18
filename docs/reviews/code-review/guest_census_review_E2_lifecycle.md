# Guest-Census Cycle — Review E2 (Lifecycle / Boot Ordering / Restart / Concurrency)

- **Tip reviewed:** `7e3fa18d055bbeb305d3baaa627ff3be1c0b8a53` (`feature/guest-census`)
- **Diff base:** `git merge-base develop feature/guest-census` = `3b373d3db7eb2d489645f2304d96fbd9da88b4f5` (verified)
- **Framing:** E — lifecycle, boot ordering, config-entry reload, RestoreEntity, re-entrancy, timezone.
- **Prior E pass:** `docs/reviews/code-review/guest_census_review_E_lifecycle.md` @ `dcf4b3d09` returned DO-NOT-SHIP on E-CRIT-1 (dead `_is_known_person_in_room` — wrong CM key + wrong attribute) + three MEDIUMs.
- **Suite (orchestrator-authoritative, not re-run):** 26 failed / 9193 passed at tip; +8 passed vs prior tip, 0 new failures.
- **Targeted drill (this pass):** `test_guest_census_correctness.py` 33/33, `test_v472_feature_b_guest_signal.py` 44/44, PYTHONDONTWRITEBYTECODE=1 + `__pycache__` purged.

## Verdict — SHIP (2 MEDIUM, 1 LOW; no CRIT/HIGH lifecycle findings)

The CRIT (dead helper) is genuinely fixed and the fix is lifecycle-sound:
canonical lookup + real attribute now match the 7 sibling call sites; sticky
cache init/clear paths are complete; re-entrancy is safe on the single-loop
callback model; tz handling is aware-on-both-sides. Two MEDIUMs remain
worth acknowledging (operator-reload contract, 300s still evidence-shaped not
evidence-having); one LOW cosmetic. None block ship.

---

## Fix-surface attack — item by item (matches prompt numbering)

### 1. Setup ordering — is `hass.data[DOMAIN]["person_coordinator"]` populated when `_guest_room_gate_armed` first runs? — SOUND (with a caveat, not a defect)

- `person_coordinator` is created and STORED at `__init__.py:2346-2348`, and
  `await person_coordinator.async_config_entry_first_refresh()` completes
  BEFORE `hass.data[DOMAIN]["person_coordinator"] = ...` at line 2348.
- `PresenceCoordinator` is not constructed until `__init__.py:2860`, then its
  `.async_setup()` runs later still, during which `_discover_guest_rooms()`
  is invoked at `presence.py:2562`.
- So `hass.data[DOMAIN]["person_coordinator"]` is guaranteed non-None by the
  first invocation of `_is_known_person_in_room` (both from
  `_discover_guest_rooms` boot-seed and from `_guest_room_gate_armed`
  live re-check via `_run_inference`).
- **What is NOT guaranteed** is that `person_coord.data[name]["location"]`
  is populated with a real room string at that instant. `async_config_entry_first_refresh`
  runs one poll; underlying person entities can still be `unavailable` /
  `unknown` at cold boot, in which case `pc.data[name]["location"]` is
  `""` / `"unknown"` / `"away"` — all now correctly filtered by the
  fix's new guard `if not location or location in ("unknown", "away", ""):`
  and `_is_known_person_in_room` returns False.
- **Implication:** at cold boot the only defense against a false-GUEST arm
  for a stationary resident in an `is_guest_room=True` room is
  `GUEST_BOOT_SEED_MIN_RESIDUAL_S=300` — the sticky cache is empty
  (no prior True to sticky-hold), and `_handle_guest_room_occupancy_change`
  does NOT fire for a stationary occupant (no state edge).
- **What saves it:** `_run_inference` fires on multiple triggers post-boot;
  each tick re-evaluates `_guest_room_gate_armed`, which calls
  `_is_known_person_in_room` fresh. If pc.data populates within 300s
  (the operator's SLO), the gate clears the stale `first_seen` (line 5047,
  "live re-check found known person") and no false-GUEST fires.
- The 300s IS evidentially unproven still — the INFO log added in this fix
  (`_discover_guest_rooms` "boot-seed decision" line at presence.py:4784-4803)
  is the TOOLING to prove it, not proof itself. That is **E2-MED-1** below.

### 2. `_guest_room_known_last_true` lifecycle — SOUND

- **Init:** `__init__` at `presence.py:1644` — always present on a real
  `PresenceCoordinator()` construction (only one production construction site,
  `__init__.py:2860`). Cannot AttributeError from prod path.
- **Cleared in `_discover_guest_rooms`** (`presence.py:4717`) — correct;
  reconfigure/re-discovery resets the cache alongside `_guest_room_state`,
  `_guest_room_unsubs`, and `_guest_room_entity_to_name`. No stale carry.
- **Cleared in `async_teardown`** (`presence.py:7213`) — correct; symmetric
  with the other three guest-room dicts cleared in the same teardown block.
- **Reload safety:** a CM-entry reload destroys the `PresenceCoordinator`
  instance and constructs a new one — the dict cannot survive a reload and
  carry a stale True across it. RAM-only, no RestoreEntity coupling.
- **Test `__new__` sites:** verified 7/7 in `test_guest_census_correctness.py`
  and 1/1 in `test_v472_feature_b_guest_signal.py` explicitly assign
  `pc._guest_room_known_last_true = {}` after `PresenceCoordinator.__new__`.
  Zero missed sites — no test-path AttributeError.
- **Write path:** the ONLY write is inside `_is_known_person_in_room`
  after a live-True (`presence.py:4985`). No other writer. Cannot get poisoned
  by a False observation.

### 3. Re-entrancy on `_handle_guest_room_occupancy_change` / inference task — SOUND

- `_handle_guest_room_occupancy_change` is a `@callback`, runs on the event
  loop thread — HA serializes callbacks. Between two occupancy events,
  `state_dict` mutations complete atomically.
- `_run_inference` is `async_create_task`'d — two consecutive occupancy
  events queue two inference tasks. Tasks can interleave at `await` points,
  BUT `_is_known_person_in_room` is a **synchronous** helper with no awaits;
  its read of `pc.data`, its filter loop, and its write to
  `_guest_room_known_last_true[room_name]` all complete inside one sync
  call — no coroutine can preempt mid-loop. Sticky-cache read/write cannot
  race.
- Producer-during-evaluation concern (prior E-MED): `_guest_room_gate_armed`
  writes `state_dict["first_seen"] = None` and `current_occupancy_known = True`
  during evaluation when the live re-check finds a known person, AND the
  fix now also writes to `_guest_room_known_last_true` inside the same
  synchronous chain. Both writes are on the loop thread; both are
  idempotent (setting first_seen to None twice is a no-op; refreshing the
  sticky timestamp to `dt_util.utcnow()` twice is a monotone update).
  No inconsistent exclude/arm decision possible from re-entry.

### 4. Options-flow reload — MEDIUM: operator contract gap (E2-MED-2)

- `_discover_guest_rooms` is called **once**, from `PresenceCoordinator.async_setup`
  (`presence.py:2562`). Grep confirms zero other invocation sites in
  production code.
- If the operator flips `CONF_ROOM_IS_GUEST_ROOM=True` via the ROOM entry's
  options-flow, the reload cascades to the ROOM entry — but `PresenceCoordinator`
  lives on the CM entry. Its `async_setup` does not re-run. The newly-guest
  room does not get discovered, no listener is registered, `_guest_room_state`
  does not include it, and `_guest_room_gate_armed` cannot arm for it.
- **Operator contract:** flipping `is_guest_room` requires a URA restart
  (or a CM-entry reload — which per memory is a watchdog hazard and
  reload-suppression allowlisted, so probably ends up being a HA restart
  anyway).
- **Rating MEDIUM (not HIGH):** feature is currently inert (no room
  currently designated per commit message), and the reverse — flipping
  from True → False — is safer than the True → False case because the
  active listener just no-ops on future events; existing `state_dict`
  entry becomes orphan but harmless (first_seen cleared on next unoccupied
  state change; sticky cache expires naturally in 120s). Doc-only fix
  or a lightweight `async_reload_guest_rooms` hook off options-update
  listener would close it; do not block ship.

### 5. Kill-switch `GUEST_KNOWN_STICKY_S=0` and `_guest_detection_enabled` toggle — SOUND

- `_is_known_person_sticky` early-returns False when `sticky_s <= 0`
  (`presence.py:4998-4999`). Writes to `_guest_room_known_last_true`
  in `_is_known_person_in_room` still occur regardless of sticky_s
  (the const is read only in the fallback), which is defensively fine —
  when the operator toggles sticky_s back up, the cache is pre-warmed by
  any prior in-cycle live-True and immediately provides latch behavior.
  No stale-state re-arm hazard: a live-True is still a legitimate
  exclusion signal at the moment it was written.
- `_guest_detection_enabled=False`: `_guest_room_gate_armed` calls
  `_clear_guest_room_first_seen()` and returns False (`presence.py:5023`).
  Toggle back to True: `first_seen` re-arms fresh on the next occupancy
  edge, sticky cache values (if any) still act as exclusions where
  legitimate. No stale-first_seen carry that could immediately fire.

### 6. Timezone consistency — LOW cosmetic (E2-LOW-1)

- `_is_known_person_in_room` writes and `_is_known_person_sticky` reads
  both use `dt_util.utcnow()` — consistent aware-UTC.
- The B-MEDIUM-1 boot-seed clamp block uses `datetime.now(timezone.utc)`
  (`presence.py:4761 area`), which is also aware-UTC. Both are equivalent
  aware datetimes; comparison paths (`last_changed >= earliest_allowed`,
  `dt_util.utcnow() - last_true`) never mix naive+aware. No production
  bug. Style-only inconsistency; harmonize to `dt_util.utcnow()` in a
  future cleanup, do not block ship.

---

## Sticky-cache lifecycle — direct answer

**Sound.** Init at `__init__`, cleared at both `_discover_guest_rooms` and
`async_teardown`, cannot survive a CM-entry reload (instance is
destroyed), cannot be missed at any test `__new__` site (verified 8/8),
cannot race under HA's single-loop callback+task model, cannot be
poisoned by a False observation (only written on live-True), and cannot
cause stale re-arm on kill-switch toggle (the value in cache is a
correct historical fact — the resident WAS there at that timestamp —
whose latch semantics are bounded by the module const window).

## 300s residual clamp — direct answer

**Defensible as an SLO; still not empirically proven.** The fix's live
re-check (Part 1) means the 300s no longer has to be perfect — the gate
re-evaluates each inference tick and will clear a stale `first_seen`
the instant `pc.data[name]["location"]` lands in the guest room. The
300s is now a floor on how long the fresh boot-seeded `first_seen`
would take to fire absent any live re-check exclusion; if pc-populate
latency is < 300s (the operator's stated SLO), no false-GUEST can arm.
The fix ADDS the INFO-log tooling to measure real populate latency in
production (`presence.py:4784-4803`) — that is the correct instrument,
but the number itself remains evidentially unproven until 1-2
representative cold boots produce log data. **This does not block ship**;
the value is Bug-Class-#53-adjacent (a knob with no empirical backing),
but it is a floor with correct kill-switch semantics and independent
defenses layered on top.

---

## Findings summary

| ID          | Sev    | Summary                                                                                                                                       | Action                                       |
|-------------|--------|-----------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------|
| E2-MED-1    | MEDIUM | `GUEST_BOOT_SEED_MIN_RESIDUAL_S=300` remains evidentially unproven. Fix adds the INFO log to measure it — collect 1-2 cold-boot samples post-ship and back-write the number into `docs/readmes/README_v<vers>.md` validation table. | Post-deploy live-validation task (not a code fix). |
| E2-MED-2    | MEDIUM | Flipping `CONF_ROOM_IS_GUEST_ROOM=True` via options-flow does not re-run `_discover_guest_rooms` (only called from `PresenceCoordinator.async_setup`). Operator contract is "requires URA restart". | Document in release notes; optional future cycle to add options-update reactor. |
| E2-LOW-1    | LOW    | Cosmetic tz inconsistency: `datetime.now(timezone.utc)` in the boot-seed clamp vs `dt_util.utcnow()` in the sticky cache. Both aware-UTC; no bug.  | Harmonize in a future janitor pass.          |

## Prior-E items — status

| Prior E finding       | Status at 7e3fa18d0 |
|-----------------------|---------------------|
| E-CRIT-1 dead helper  | **FIXED** — canonical `hass.data[DOMAIN]["person_coordinator"]` + real `data[name]["location"]`; sibling-consistent with 7 other sites; drill-anchored by two revert-drill tests. |
| E-MED-2 reload paths  | **UNRESOLVED — carried as E2-MED-2** (options-flow flip still requires restart). |
| E-MED gate-as-producer re-entrancy | **RESOLVED** — sync helper, single-loop, idempotent writes. Documented above (§3). |
| E-MED unproven 300s   | **PARTIALLY RESOLVED — carried as E2-MED-1** (tooling added, evidence pending). |

## Drill evidence

- Environment: PYTHONDONTWRITEBYTECODE=1; `find . -type d -name __pycache__ -exec rm -rf {} +`; tip checked out to worktree; `git status` clean after restore.
- `pytest quality/tests/test_guest_census_correctness.py` → **33 passed** (0.12s).
- `pytest quality/tests/test_v472_feature_b_guest_signal.py` → **44 passed** (0.10s).
- Full-suite deltas taken from orchestrator (26f/9193p at tip; +8p vs prior tip; 0 new failures) — hook denies concurrent full-suite runs; not re-run per protocol.

## Ship decision

**SHIP.** The CRIT is genuinely repaired, the fix does not add lifecycle
hazards, and the two remaining MEDIUMs are (1) a post-deploy evidence
task, not a code defect, and (2) a documented operator contract (a
`is_guest_room` flip needs a restart) — both acceptable at ship.
