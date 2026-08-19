# Review B — Integration + state-machine + no-inverse-deadlock

**Cycle:** FAN-RECHECK-D2-DEADLOCK-1 (folds in FAN-RECHECK-SLEEP-VETO-SCOPE-1)
**Reviewer framing:** B — end-to-end tick-by-tick trace across the D2 ↔ recheck boundary; does the fix break the primary deadlock without opening a symmetric inverse deadlock; state-machine integrity across all reachable transitions; cross-coordinator side-effects of D2 deferring; v4.7.13 keep-on contract byte-identical for bedrooms; boot / restart edges.
**Branch reviewed:** `feature/fan-recheck-deadlock` @ `ce4437c69`
**Diff base:** `develop...HEAD` (5 files, +583 / -86)
**Date:** 2026-08-19

---

## 0. TL;DR verdicts (B's load-bearing claims)

| Claim | Verdict |
|---|---|
| **Does the fix actually break the D2 ↔ recheck deadlock?** | **YES** — end-to-end trace holds. |
| **Does it open a symmetric inverse deadlock** (fan-ghost room permanently occupied because D2 defers forever)? | **NO** — every eligibility gate that CAN'T clear the room returns False → D2 fires as backstop. Every recheck terminal state (vacated / occupied_confirmed / aborted → cooldown) returns to `STATE_IDLE`, which un-latches `recheck_in_flight`. |
| **Preserved-invariant regression:** v4.7.13 bedroom-keep-on across `FAN_TRUST_STATES`? | **PRESERVED** — new predicate is `house_state in FAN_TRUST_STATES AND room_type == ROOM_TYPE_BEDROOM`, symmetrically applied in `_evaluate_eligibility` (:485) AND `_still_armed_eligible` (:965). |
| **State-machine integrity** on the `_mmwave_fan_demoted_last_tick` outer-else preservation? | **CLEAN** — the removed outer `else` (`coordinator.py:3618` in the old file) is faithfully migrated into the new `if recheck_in_flight or recheck_eligible:` defer branch (:3441). Semantically byte-identical for the `recheck_in_flight`-only branch. |
| **Cross-coordinator ripple** from D2 deferring? | **NONE** — deferral means D2 does not overwrite `data[STATE_OCCUPIED]`; other consumers (zone aggregator, HVAC, safety, energy) read the same mmwave-truth value they would have read pre-D2. The defer is the "no-change" branch. |
| **D3 per-room isolation** — genuine, no shared-state corruption? | **CLEAN** — per-iteration try/except at WARNING; `on_room_tick` returns None and mutates only per-room ctx state (verified). |

**Verdict: SHIP.** Findings below are LOW / observability only; none block deploy.

---

## 1. End-to-end tick trace — deadlock BREAK

Precondition: Living Room, fan on ≥ grace, PIR-stale ≥ 2× timeout, mmwave-sole for ≥ N ticks, master + room fan-recheck enabled, `fan_control_enabled=True`, no BLE L1/L2, non-bedroom, house_state ∉ trust-states, boot-settle done, no manual cooldown, rate-cap free, person_coord ready.

### Pre-fix (deadlock)

| Tick | D2 (`coordinator.py:3368-`) | Recheck driver (`presence.py:6890-`, 60s cadence) |
|---|---|---|
| N | demoted=True, `_state == idle` → `recheck_in_flight = False` → fire → `data[STATE_OCCUPIED] = False` | (independent cadence — no driver tick this second) |
| N+1 | same → fire again | driver fires → `on_room_tick` → `_is_eligible` → `data.get("occupied")` FALSE → `veto("not_occupied")` → stays IDLE |
| N+2 | fire | eligible-check keeps failing (mmwave decayed OR still False from D2) |

Result: **recheck never leaves idle**; matches live evidence `veto_counts={not_occupied:1}, eval_count=1`.

### Post-fix (deadlock broken)

| Tick | D2 flow | Recheck flow |
|---|---|---|
| N | demoted=True, `_state == idle` → `recheck_in_flight=False`; **NEW:** `is_recheck_eligible(room)` runs `_evaluate_eligibility(..., _INERT_SINK)` → all 9 gates pass (occupied=True still, because D2 hasn't fired yet) → returns True → `recheck_eligible=True` → **defer** (`_mmwave_fan_demoted_last_tick=False`; DEBUG "defer:eligible"). **`data[STATE_OCCUPIED]` NOT overwritten** → stays True. | idle |
| N+1..N+k (D2 fires each ~10s room-coord tick) | Same: eligible=True → defer → occupied stays True | idle (waiting for 60s driver) |
| Driver tick T (≤60s later) | (D2 still deferring) | `on_room_tick` → `_is_eligible` (live sink) → all 9 gates pass → `_enter_armed` scheduled → `ctx.state=STATE_ARMED` |
| T+ε | `get_room_state == "armed"` → `recheck_in_flight=True` → defer via first gate (DEBUG "defer:in-flight") | ARMED, timer_unsub scheduled for `ARM_DELAY_S=60s` |
| T+ARM_DELAY (=T+60s) | still `recheck_in_flight` → defer | `_on_arm_expired` → `_still_armed_eligible` → all gates pass → `_enter_paused` → fan paused → `ctx.state=STATE_PAUSED` |
| T+ARM_DELAY+WINDOW (=T+~180s incl. spindown) | still in_flight → defer | `_on_window_expired` → observed empty → `_enter_restoring` → `apply_fan_recheck_release` → `data[STATE_OCCUPIED]=False`, source=`fan_recheck_release` → `_enter_cooldown` |
| Cooldown period (`DEFAULT_FAN_RECHECK_COOLDOWN_S`) | `_state == "cooldown"` → in_flight=True → defer (occupancy now legitimately False; D2 has nothing to do) | `ctx.state=STATE_COOLDOWN` |
| Post-cooldown | `_state == "idle"` → `recheck_in_flight=False`; `is_recheck_eligible` → `occupied=False` → `veto("not_occupied")` → False → **D2 fires as backstop** if room is genuinely still fan-ghost-empty. But room is already `occupied=False` from the recheck release, so no work for D2. | IDLE |

**Upper bound T** (matches plan §3.2.3): `60s driver + 60 ARM + ~30 spindown + 60 window ≤ 210s + D0 margin`. Confirmed by state-machine walk.

**Deadlock-break claim: PROVEN.**

---

## 2. Inverse-deadlock analysis (B's #1 risk)

Question: can a room stay occupied FOREVER because `is_recheck_eligible` returns True indefinitely and D2 never fires — even when recheck cannot complete?

Method: enumerate every eligibility gate (`_evaluate_eligibility`, presence_fan_recheck.py:454-608) AND every recheck terminal state, verifying (a) failing gate ⇒ False ⇒ D2 backstop fires, (b) every terminal state returns ctx to `STATE_IDLE` so the loop can re-close.

### Eligibility gates (in order) — failure paths

| Gate | Fail path | D2 outcome |
|---|---|---|
| `master_off` / `room_disabled` / `fan_control_off` | False | Backstop fires |
| Sleep-scoped (bedroom + FAN_TRUST_STATES) | False | Backstop fires (correct: bedroom-during-sleep protection) |
| `not_occupied` | False | Backstop fires (nothing to demote anyway if occupied False) |
| `mmwave_history_short` / `not_mmwave_sole` | False | Backstop fires (D2 also mmwave-fan-demotes, so this is the right frame) |
| `no_fan_configured` / `no_fan_on` | False | Backstop fires |
| `boot_settle` | False | Backstop fires (D2 has its own boot gate — no double-defer) |
| `manual_off_cooldown` | False | Backstop fires |
| `rate_cap` | False | Backstop fires |
| `no_person_coord` | False | Backstop fires |
| `ble_l1` | False | Backstop fires (real person → D2 fires; occupancy demotion is DESIRED here; NOTE: this is a pre-existing behavior — see finding B-LOW-3) |
| Tier-1 `high_still_risk` / `ble_l2` | False | Backstop fires |
| Tier-2/0 `ble_l2` / `high_still_risk` / `trust_sensors_off` | False | Backstop fires |
| **All pass** (Tier-1 no zone_persons OR Tier-1 L2-allowed non-high-still OR Tier-0/2 all clear) | True | Defer → recheck arms → completes → cooldown → idle → loop closes |

**Enumeration complete. Every False path lands on D2 backstop; every True path proceeds through recheck's own terminal state machine to `STATE_IDLE`.**

### Recheck terminal states → back to IDLE

Verified in-source (presence_fan_recheck.py):
- `_enter_cooldown` (:848) → schedules `_on_cooldown_done` (:860) → `ctx.state = STATE_IDLE` (:862).
- Restart / re-hydration paths (:1318, 1340, 1350, 1355, 1372, 1374) → all end at `STATE_IDLE`.
- `force_restore` (:317) — operator escape, ends in cooldown → idle.

No terminal state leaves ctx stuck non-idle. ✅

**Inverse-deadlock claim: NEGATED. The fix cannot produce a fan-ghost room permanently latched occupied.**

---

## 3. State-machine integrity — the `_mmwave_fan_demoted_last_tick = False` preservation

Old code (`coordinator.py`):
```
if not recheck_in_flight:
    # ... demotion body ...
else:
    self._mmwave_fan_demoted_last_tick = False   # ← removed by this diff
```

New code (`coordinator.py:3438-`):
```
if recheck_in_flight or recheck_eligible:
    self._mmwave_fan_demoted_last_tick = False   # ← new inline
    if DEBUG: log
else:
    # ... demotion body (unchanged) ...
```

Trace:
- Old `recheck_in_flight=True` path → outer `else` → `= False`. NEW: `in_flight=True` → new defer branch → `= False`. **Byte-identical semantic.**
- Old `recheck_in_flight=False, eligible=False` path → outer `if` → demotion body. NEW: `False or False` → outer `else` → demotion body. **Byte-identical.**
- Old `recheck_in_flight=False, eligible=True` path → outer `if` → demotion body (this is the DEADLOCK). NEW: `False or True` → new defer branch → `= False` + log. **THIS is the fix.**

No state drift. Correctness of the `= False` reset preserved across the refactor. ✅

---

## 4. v4.7.13 keep-on contract — bedroom preservation

Old sleep veto: `house_state == HouseState.SLEEP` (both sites).
New sleep veto: `house_state in FAN_TRUST_STATES and room_type == ROOM_TYPE_BEDROOM` (both sites).

Applied symmetrically:
- `_evaluate_eligibility` (:485) — arm gate.
- `_still_armed_eligible` (:965) — abort gate at `_on_arm_expired`.

Behavioral matrix:

| house_state | room_type | Old veto | New veto | Delta |
|---|---|---|---|---|
| SLEEP | bedroom | veto | veto | preserved |
| SLEEP | non-bedroom | veto | **no veto** | INTENTIONAL fix (D2 fold-in) |
| HOME_NIGHT | bedroom | no veto | **veto** | INTENTIONAL widening (v4.7.13 trust states) |
| HOME_NIGHT | non-bedroom | no veto | no veto | preserved |
| WAKING | bedroom | no veto | **veto** | INTENTIONAL widening (v4.7.13 trust states) |
| WAKING | non-bedroom | no veto | no veto | preserved |
| HOME_DAY / AWAY / etc | any | no veto | no veto | preserved |

The two "widening" deltas (bedroom / HOME_NIGHT + bedroom / WAKING) are correct: v4.7.13 keeps bedroom fans running through ALL of `FAN_TRUST_STATES`; the pre-fix code was ALREADY subtly wrong (it protected bedroom fans only during SLEEP, not home_night/waking). New predicate aligns with `hvac_fans.py:1205-1209` — the source of truth. ✅

**In-flight bedroom cycle at sleep edge:** verified `_still_armed_eligible` now catches it (:965 predicate matches :485). If a bedroom room arms just before HOME_NIGHT begins, the ARM_DELAY expiration re-checks and enters cooldown instead of pausing the fan. Preserved.

---

## 5. Cross-coordinator ripple — what OTHER consumers of `data[STATE_OCCUPIED]` see

D2 deferring means the D2 write `data[STATE_OCCUPIED]=False` **does not happen** on that tick. Consequence: the same value that WOULD have been produced without D2 (i.e., the mmwave-driven `True`) is what downstream consumers read.

Consumers (verified — no diff changes) — all consume the room-coord `data` dict via the presence/HVAC/energy/security stack:
- **Zone aggregator (`_room_occupied`)** — sees True (unchanged from mmwave truth). Zone-tier occupied stays True. Downstream: HVAC/energy zone gates keep the room "occupied" for another tick (up to `T ≤ 210s`). This is the intended semantic — the recheck is precisely the arbiter deciding whether that occupancy is real or a fan-ghost.
- **HVAC** (`hvac.py`, `hvac_fans.py`) — reads occupied via room/zone. Same value it would read without D2. **No new fan-cycling risk introduced.**
- **Safety / energy / compliance** — read occupied via room-coord. Unchanged.
- **D-PRIME-CRIT-1 D1 hold** (referenced in the diff comment at :3413-) — re-stamped every tick while fan-suspect. Deferring D2 doesn't clear the hold; hold is re-stamped normally. When D2 eventually DOES fire (post-cooldown, or backstop path), it atomically clears the hold (unchanged code path at :3459+).

**No cross-coordinator behavior change from deferral.** Deferral IS the pre-D2 baseline for one tick.

---

## 6. Race / lifecycle checks

- **D2 read of `is_recheck_eligible` (sync, room-coord update path) vs recheck async state transitions**: HA event loop is single-threaded; async transitions interleave at await boundaries. Between the D2 read (which returns a snapshot) and the next D2 read (~10s later), the recheck may transition idle→armed. On the NEXT D2 tick, `get_room_state` reads the new state → `recheck_in_flight=True` → defer via first gate. OR-composed guard handles the interleave. **No race.**
- **No double-arm hazard**: `on_room_tick` early-returns if `ctx.state != STATE_IDLE` (:305). D2's eligibility read does not schedule arm; only `_enter_armed` does. Path is serialized through the presence 60s driver. ✅
- **Boot-settle**: recheck's `_boot_settle_done` gate (:520) → returns False → eligibility False → D2 backstop fires. D2 has its own boot-settle machinery (`_d2_boot_settle_done`). No interaction hazard: during boot, both gates independently veto; whichever opens first fires.
- **`_setup_done`**: `is_recheck_eligible` early-returns False if `not self._setup_done` (:398). D2 falls back to backstop. ✅
- **Restart / re-hydration**: `_evaluate_eligibility` uses ephemeral `_RoomCtx` if `_rooms.get()` is None (line 411-415). Note: attempts list is empty on ephemeral ctx (see finding B-LOW-1). Restart re-hydration paths correctly reset ctx.state to IDLE per lines 1318/1340/1355/1372/1374.
- **Timer cleanup**: `_enter_cooldown` schedules a single timer; timer_unsub cleanup unchanged. ✅

---

## 7. D3 — per-room exception isolation

`presence.py:6893-6928`:
- Outer read guard: `async_entries(DOMAIN)` in try/except → WARNING on failure → `entries = []` → loop no-ops. ✅
- Per-room try/except at WARNING (per-iteration). `on_room_tick` returns None (no downstream contract; verified: nothing consumes its return). ✅
- Shared state: none. `on_room_tick` writes only to `self._rooms[room_name]` (per-room ctx), `self._eval_counts[room_name]`, and schedules a per-room async task. No cross-room mutation. A mid-loop exception cannot corrupt sibling ctx. ✅

**D3 clean.**

---

## 8. Findings

### B-LOW-1 — Ephemeral ctx bypasses per-room rate-cap on read-only path

**File:** `presence_fan_recheck.py:411-415`
**Severity:** LOW (observability / conservatism drift; not a correctness bug)
**Bug class:** Read-path fixture drift

`is_recheck_eligible` falls back to constructing an ephemeral `_RoomCtx(...)` when `self._rooms.get(room_name) is None`. That ctx has empty `attempts`, so the `rate_cap` gate can never fail on the read-only path for a room whose live ctx does not yet exist.

**Impact:** In practice, `_rooms[room_name]` is populated on the first `on_room_tick` call (:301) — well before D2's PIR-stale gate can fire (D2 requires `fan-on >= grace AND PIR-stale >= 2x timeout`, giving many minutes of prior `on_room_tick` runs). No realistic exposure to reach D2's demotion gate before recheck has seen the room. **No action required.** Documenting for future audit.

### B-LOW-2 — `is_recheck_eligible` does not short-circuit on `ctx.state == STATE_COOLDOWN`

**File:** `presence_fan_recheck.py:378-419`
**Severity:** LOW (belt-and-suspenders; masked by existing `recheck_in_flight` OR)
**Bug class:** Redundant work

When ctx is in COOLDOWN, `is_recheck_eligible` evaluates all 9 gates. Result doesn't matter — the sibling `recheck_in_flight` gate is already True in cooldown → D2 defers via first gate. Wasted work but not a correctness issue.

**Impact:** Negligible. Adding `if ctx.state in (STATE_ARMED, STATE_PAUSED, STATE_RESTORING, STATE_COOLDOWN): return False` at the top of `is_recheck_eligible` would save a merged-config + person-coord scan per D2 tick per in-flight room. **Optional micro-opt.**

### B-LOW-3 — `ble_l1` veto → D2 backstop demotes a room with a trustworthy L1 person (pre-existing)

**File:** `presence_fan_recheck.py:555-559` (fail path) → D2 fires as backstop
**Severity:** LOW (pre-existing behavior; not introduced by this diff)
**Bug class:** N/A — noted for framing-B completeness

If a trustworthy L1 person is in-room, `_evaluate_eligibility` returns False → `is_recheck_eligible` returns False → D2 fires. If the room ALSO meets D2's bar (PIR-stale, mmwave-sole, no motion), D2 demotes occupancy to False. This overrides the trustworthy L1 signal.

**Impact:** Pre-existing pre-fix behavior — the deadlock previously masked it (D2 always fired regardless). Post-fix, the same behavior holds because L1-present → eligibility False → backstop → same outcome as pre-fix. **No regression.** Whether D2 SHOULD outrank L1 is a separate cycle question. Not this cycle's scope.

### B-INFO-1 — Two reads of `merged.get(CONF_ROOM_TYPE, ...)` in the same function

**File:** `presence_fan_recheck.py:482, 563`
**Severity:** INFO
**Bug class:** DRY

`room_type_early` (:482) and `room_type` (:563) are the same value from the same merged dict. Cosmetic; not a bug.

---

## 9. Framing-B verdict

**SHIP.**

- Deadlock is broken end-to-end by the OR-composed defer (eligible + in-flight). Trace verified across sync D2 tick, async presence driver, and each ctx-state transition.
- No inverse deadlock is opened: every eligibility failure path routes to D2 backstop; every recheck terminal state returns to STATE_IDLE.
- The `_mmwave_fan_demoted_last_tick = False` outer-else preservation is byte-identical for the pre-existing `recheck_in_flight` path.
- v4.7.13 bedroom-keep-on contract is preserved and correctly widened to `FAN_TRUST_STATES`, symmetrically at the arm and the `_still_armed_eligible` sites.
- No cross-coordinator ripple: D2 deferring is the pre-D2 no-op branch for that tick.
- D3 per-room isolation clean; no shared mutable state across iterations.
- Boot-settle, restart re-hydration, and race interleaves all handled.

All findings are LOW / observability / pre-existing and none block deploy. Reviewer A (local correctness) and Reviewer C (test authority + mutation anchoring) should independently confirm their framings; my framing sees no blocking finding.
