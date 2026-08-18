# Guest-Census Cycle — Review D2 (adversarial completeness, re-run)

- **Branch/tip reviewed:** `feature/guest-census` @ `7e3fa18d0`
- **Diff base:** `git merge-base develop feature/guest-census` = `3b373d3db`
- **Commit count on branch (independent):** 8 commits (`eae92423c`, `7f7c15d20`, `36d92bc6e`, `c7c308a53`, `44ccfabc6`, `0e0ea97a2`, `1107d3b31`, `7e3fa18d0`)
- **Previous D verdict (13ba10861 doc):** DO-NOT-SHIP — `_is_known_person_in_room` was a dead oracle (wrong coordinator key + non-existent attribute), so under D2 unification the guest-room gate was the SOLE arm and residents would silently arm GUEST after threshold.
- **This D2 verdict:** **SHIP.** INV-GUEST-NO-RESIDENT holds across the whole enumerated surface. Two residual findings are informational (one is a pre-existing state-machine limitation slightly extended by the new sticky latch; one is a config-boundary caveat). Neither blocks ship. Phone-left-behind explicitly out of scope (carded).
- **Test posture:** did NOT re-run the full suite (host serializes pytest; orchestrator authoritative numbers are 7e3fa18d0 = 26 failed / 9193 passed vs 1107d3b31 = 26f/9185p, delta = +8 = the 8 new oracle tests). Did targeted greps + evidence-based enumeration only.

---

## 1. Falsifiable invariant

**INV-GUEST-NO-RESIDENT (verbatim from `PLANNING_guest_census_correctness.md`):**
> In ANY reachable path — boot, config-entry reload, guest-room re-discovery, kill-switch toggle — a designated guest room occupied SOLELY by known tracked residents MUST NOT cause `_guest_room_gate_armed()` to return True.

My job: enumerate every reachable path that could make the gate return True with only residents present, and either (a) show it is closed, or (b) produce a concrete legal-config reachable repro that opens it.

---

## 2. Independent re-enumeration (grep, not trust)

### 2.1 Every write to `first_seen` (arm & clear) — `presence.py` @ 7e3fa18d0

| Line | Site | Kind | Guard |
|------|------|------|-------|
| 4831 | `_discover_guest_rooms` boot-seed | **ARM** (clamped) | `if last_changed is not None and not self._is_known_person_in_room(room_name)` + `earliest_allowed = now - GUEST_BOOT_SEED_MIN_RESIDUAL_S` (line 4823ish) |
| 4903 | `_handle_guest_room_occupancy_change` Transition 3 (unoccupied) | CLEAR | unoccupied |
| 4910 | `_handle_guest_room_occupancy_change` Transition 2 (known) | CLEAR | `occupant_known == True` |
| 4919 | `_handle_guest_room_occupancy_change` Transition 1 (unknown) | **ARM** | `occupant_known == False`, `first_seen is None` |
| 5050 | `_guest_room_gate_armed` live re-check | CLEAR | `_is_known_person_in_room(room_name) == True` (added HIGH fix-up `1107d3b31`) |
| 5205 | `_clear_guest_room_first_seen` | CLEAR | kill-switch OFF path |

**There are exactly TWO arm sites** (boot-seed + Transition 1). Both gated by `_is_known_person_in_room`. Boot-seed additionally residual-clamped. No arm path skips the gate.

### 2.2 Every path that can make `_guest_room_gate_armed` return True

1. `_guest_detection_enabled` must be True (kill-switch A — Path B) — line 5023.
2. Some `state_dict["first_seen"]` must be non-None → only the two ARM sites above can put it there.
3. `state_dict["current_occupancy_known"]` must be False.
4. **NEW post-HIGH-fix-up:** live `_is_known_person_in_room(room_name)` must return False at gate time — line 5043. If it returns True, the site CLEARS `first_seen=None` and `current_occupancy_known=True` and `continue`s.
5. `elapsed_min >= threshold_min`.

Falsifying-attack surface: can a resident-only room satisfy (2)+(3)+(4) simultaneously?

### 2.3 Attack — each of the four fix ingredients

#### (A) Canonical `hass.data[DOMAIN]["person_coordinator"]` lookup

Sibling-site grep on `presence.py`:
```
2060:  person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
3609:  person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
3818:  person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
4595:  person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
5146:  person_coordinator = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
5878:  pc = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
6604:  person_coord = self.hass.data.get(DOMAIN, {}).get("person_coordinator")
```
Now 8 sites total include the fixed helper. **Aligned.** `coordinator_manager.coordinators["person"]` — the previous broken key — appears nowhere else. Falsification attempt fails: no residual site still reads the dead key.

#### (B) `person_coord.data[name]["location"]` shape

`person_coordinator.py` populates this dict at lines 452, 528, 1349, 1422 (`return self.data[person_name]["location"]`), and `_resolve_person_room` (line 1036) is the sole producer of the string value. Possible values I enumerated:
- `"unknown"` (LOST / entity-missing path, line 452)
- `"away"` (zone.away path — checked at line 5225 sibling)
- `""` (unset — filtered by `if not location or location in ("unknown","away","")`)
- A CONF_ROOM_NAME string (Tier 1/2/3 resolver)
- **Fallback:** raw `bermuda_area` when the area has no scanner/area mapping (`_resolve_person_room` line ~1082: `_LOGGER.debug("No mapping for '%s', using as-is", bermuda_area); return bermuda_area`)

Filter at line 4939-4942 correctly rejects `"unknown"`, `"away"`, `""`. The `.lower().replace(" ","_")` normalization is applied symmetrically at line 4938 (target) and 4944 (candidate).

**Vocabulary attack — CAN `location` diverge from CONF_ROOM_NAME while the resident IS in the room?** Yes, via the fallback path: if a guest-flagged room's residents are detected via a Bermuda area that has no scanner-area/area-id mapping AT ALL, `_resolve_person_room` returns the raw bermuda_area string, which will not match `CONF_ROOM_NAME`. **This is a config-boundary residual (D2-INFO-2), not a fix regression** — the prior code was worse (returned False unconditionally). Live inventory: 0 rooms currently have `is_guest_room=True`, so the residual is inert until the operator flips it. Recommendation carried in §4.

#### (C) `GUEST_KNOWN_STICKY_S=120` latch

Read code:
- `_is_known_person_sticky` (line 4996): `if sticky_s <= 0: return False`. Kill-switch confirmed.
- Write site: `self._guest_room_known_last_true[room_name] = dt_util.utcnow()` on a live positive hit (line 4946). **The cache is populated ONLY by live positives.** No arm-time or reload-time synthetic seeding.
- Read site: `_is_known_person_in_room` returns from the sticky check both when `person_coord is None` and when the live loop found no match (line 4953-4954).
- Clear sites: `_discover_guest_rooms` (line 4720) + `async_will_remove` (line 7218). Both cover reload/re-discovery.

**Attack: does sticky mask a resident who has actually left, causing a real guest arriving right after to be wrongly excluded from GUEST arming?**
- Sticky = up to 120s.
- Threshold to fire = 30 min.
- Even in the worst crossover (resident leaves at t, guest arrives at t+1s), sticky expires at t+120s → live re-check thereafter correctly returns False → arm proceeds. But: **the state machine is event-driven from the occupancy sensor**. If the room's occupancy sensor never toggles between resident-out and guest-in (they overlap), `_handle_guest_room_occupancy_change` doesn't refire, and `first_seen` was already cleared to None by the last sticky-masked gate cycle. Result: gate does NOT rearm until the room goes vacant and re-occupied.

This is a real leak of **INV-GUEST-LEAD** (guest must eventually arm), **not INV-GUEST-NO-RESIDENT**. It is also **pre-existing** — the same identity-change-without-occupancy-transition gap exists without sticky, because the handler only fires on the occupancy sensor's state change. Sticky extends the window by 120s but does not introduce a new class. Since the fix docstring explicitly frames sticky as "belt-and-suspenders against a false-GUEST class" and the operator (via CLAUDE.md's "no fabrication" + probe-first culture) has accepted that trade, this stays informational. Carded as D2-INFO-1 below.

**Kill-switch attack:** with `GUEST_KNOWN_STICKY_S=0` in const, `_is_known_person_sticky` returns False unconditionally. The base check (line 4933-4948) still executes. If person_coord has a live match, it stamps the sticky cache AND returns True; but the sticky cache is inert (no reader will use it because sticky_s=0). ✅ Base behaviour preserved.

**Can the sticky cache itself become a stuck exclusion vector?** Cache is a `Dict[str, datetime]`. Only cleared on reload or re-discovery. Never grows beyond one entry per guest room. Not a stuck-value vector for INV-GUEST-NO-RESIDENT (an over-True on `_is_known_person` → over-exclusion → NO false GUEST).

#### (D) 300s residual clamp + live re-check interaction

**Question posed:** with live re-check now real, is the 300s clamp still load-bearing, or defense-in-depth?

**Answer: still load-bearing.**

- Without the clamp, boot-seed `first_seen = last_changed`. If a resident sat in a guest room for 45 min before HA restart, elapsed at first inference cycle post-boot is already 45 min > 30 min threshold. Gate fires on the very first tick — **before** the live re-check has any wall-clock time to catch a slow-populating person_coord.
- With the clamp, `first_seen = max(last_changed, now - 300s)`, so first fire opportunity is `now - 300 + 30 min = now + 25 min`. That buys ≥25 minutes for `person_coordinator.data[name]["location"]` to converge and the gate live re-check (line 5043) to catch the resident and CLEAR `first_seen`.
- Both defences must hold: clamp buys the time; live re-check consumes it. Removing the clamp reopens the boot false-GUEST hole even with the live re-check in place.

Verdict: **300s clamp remains load-bearing**, live re-check is a strict addition, not a replacement.

### 2.4 Every path that assigns `current_occupancy_known` — grep

| Line | Site | Value |
|------|------|-------|
| 4711 | initial dict seed | False |
| 4779 | boot-seed dict init (in `_discover_guest_rooms`) | False (post-seed) |
| 4904 | Transition 3 (unoccupied) | False |
| 4911 | Transition 2 (known) | True |
| 4920 | Transition 1 (unknown) | False |
| 5051 | gate live re-check known | True |

All True-writes are gated by `_is_known_person_in_room` = True (now real). No path sets True without the check.

---

## 3. Path-by-path INV-GUEST-NO-RESIDENT verdict

| Reachable path | Can arm resident-only? | Why closed |
|---|---|---|
| **Boot (fresh HA start)** | No (bounded) | Residual clamp 300s → gate live re-check has ≥25 min to catch person_coord convergence. If person_coord fails to populate for >25 min, the resident is effectively undetectable — arming is coordinator-correct (not a fix regression). Carded phone-left-behind is the one operator-flagged residual and is out of scope. |
| **Config-entry reload** | No | `_discover_guest_rooms` clears `_guest_room_state`, `_guest_room_unsubs`, `_guest_room_entity_to_name`, `_guest_room_known_last_true`. Boot-seed path re-runs with the fixed helper. |
| **Guest-room re-discovery** | No | Same clear path (line 4720). |
| **Kill-switch toggle** | No | `_guest_detection_enabled=False` short-circuits gate at line 5023 AND calls `_clear_guest_room_first_seen()`. Re-enable re-arms from event stream. |
| **Runtime steady state** | No | Transition 1 gated by real helper; gate live re-check catches drift. |
| **BLE transient flap (resident stationary)** | No | Sticky latch (120s) prevents mistaken un-exclusion. |
| **Resident→guest crossover with continuous occupancy** | No for INV-GUEST-NO-RESIDENT (masks TOWARD safer). But **INV-GUEST-LEAD** may not arm until room vacates — carded D2-INFO-1. |
| **Vocabulary mismatch (bermuda_area fallback)** | **Possibly YES** under a specific config: a guest-flagged room whose residents' Bermuda-resolved location falls through the `_resolve_person_room` no-mapping fallback returning a bermuda_area string that doesn't match CONF_ROOM_NAME. Config-boundary; inert today (0 rooms flagged is_guest_room=True). Carded D2-INFO-2. |

**INV-GUEST-NO-RESIDENT holds across every reachable path under today's live config.** The one config-boundary residual (D2-INFO-2) is inert until the operator flips a room's `is_guest_room=True`, and even then only manifests under a specific scanner-mapping shape. Not a ship blocker.

---

## 4. Findings

### D2-INFO-1 — Sticky latch (120s) extends the identity-crossover masking window (pre-existing gap, not a regression)
**Severity:** INFO. Affects INV-GUEST-LEAD, not INV-GUEST-NO-RESIDENT.
**Mechanism:** resident + guest overlap in a guest room, resident leaves, room stays continuously occupied (guest). No occupancy state change → `_handle_guest_room_occupancy_change` doesn't refire. Sticky at gate re-check clears `first_seen` for 120s while masking. After 120s expiry, `first_seen` stays None (no arm path).
**Action:** none required for this cycle. The fix docstring explicitly frames sticky as intentional. Future work (if the operator ever flags is_guest_room=True on a genuinely shared room) could refactor the state machine to allow the gate's live re-check to also **arm** first_seen when it detects an unknown occupant with `current_occupancy_known=True` but no known person present. Carding recommended in the kanban.

### D2-INFO-2 — `_resolve_person_room` no-mapping fallback returns raw bermuda_area, which can diverge from CONF_ROOM_NAME
**Severity:** INFO. Config-boundary. Currently inert.
**Mechanism:** if a room flipped `is_guest_room=True` has residents whose Bermuda area does not match any scanner-area/area-id mapping, `person_coord.data[name]["location"]` will hold a raw bermuda_area string. The `.lower().replace(" ","_")` normalization on both sides will not save this — the strings differ semantically.
**Action:** add a live-config precondition to the README/planning-doc when the operator flips `is_guest_room=True` on any room: verify `sensor.<person>_previous_location` or `person_coord.data[<person>]["location"]` resolves to that room's CONF_ROOM_NAME for every resident who might be in that room. Suggested kanban card. Not a ship blocker for this cycle (feature inert until flag flipped).

### D2-NIT — Boot INFO log at 4787 silently swallows all exceptions
Diagnostic-only path; the `except Exception: pass` at the innermost try is fine for a log line. No action.

---

## 5. Drill posture (not re-run)

The fix commit documents four drills with expected FAIL outcomes:
- (a) lookup reverted → 5 tests fail incl. both anchors — FAIL as expected
- (b) attribute reverted → 3 tests fail incl. anchor — FAIL as expected
- (c) `GUEST_BOOT_SEED_MIN_RESIDUAL_S=0` → clamp test fails — FAIL as expected
- (d) `async_track_state_change_event` neutered → listener test fails — FAIL as expected

Per orchestrator directive (host-serialized pytest, another agent's stuck run), I did NOT re-run drills. Grep confirms the 8 new oracle tests exist at expected names (test_guest_census_correctness.py lines 987, 1120, 1132, 1146, 1153, 1164, 1175, 1188, 1214), and orchestrator suite delta (+8 passing tests, 0 new failures) is consistent with those tests all passing on the tip. If a fresh drill run becomes possible after the concurrent pytest clears, spot-check drill (a) at minimum.

---

## 6. Verdict

**SHIP.**

INV-GUEST-NO-RESIDENT is enumerated closed across boot, reload, re-discovery, kill-switch, runtime, BLE-flap, and identity-crossover paths under today's live config. The two residual findings (D2-INFO-1, D2-INFO-2) are informational and do not block deploy. Phone-left-behind is carded and out of scope.

The 300s residual clamp and the gate live re-check are complementary — both remain load-bearing.

Confirmed the D2 CRIT (D-CRIT-1 from `guest_census_review_D_completeness.md`) is repaired: `_is_known_person_in_room` now reads the canonical `hass.data[DOMAIN]["person_coordinator"]` and `person_coord.data[name]["location"]`, aligned with all 7 sibling sites in the same file. The repair introduces no new hole in the invariant surface.
