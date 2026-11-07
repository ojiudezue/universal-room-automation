# SC garage lockout Phase 1: Review A (local correctness, edge cases, plan invariants)

Branch `feature/sc-garage-lockout-phase1` @ 678d292e. Diff base 3153a918 (`git merge-base HEAD develop`, verified). Pre-review tag `pre-review-sc-lockout-p1` = 1247f108.
Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `docs/architecture/SENSOR_FLEET_CLASSES.md`. For `docs/QUALITY_CONTEXT.md`, the bug-class index was read, plus the classes cited below.
Plan: rev 5 + Operator answer Q-G1.

**Verdict: FIX-REQUIRED (H1, M1).** No finding breaks a safety invariant. Every defect fails toward release, which is the safe direction. H1 and M1 still silently defeat designed behaviour, and H1's tests do not model how HA really behaves.

## Findings

### H1 (HIGH): the boot "recent arrival" rule fires on every restart with a resident home
- **Where:** `security_lock_regime.py:439-451` (`_boot_rebuild`).
- **Code:** releases if any resident reads `home` with `last_changed` within 600 s.
- **Why it always fires:** HA `person` restores its state in `async_added_to_hass` (pinned HA `components/person/__init__.py:464-468`) and then writes a fresh `State`. A fresh State has `last_changed` = boot time. The state machine never restores `last_changed`.
- **Repro:**
  1. SLEEP engage at 23:30.
  2. HA restarts at 02:00. Ezinne restores `home`, `last_changed` ≈ 02:00.
  3. SC setup runs `_boot_rebuild`, which calls `_release("boot_recent_arrival")`.
  4. Both lockouts unlock for the rest of the night.
- **What it defeats:** INV-4 / H1's restart rebuild (reason sleep, wake / backstop release) is dead on every real night restart, because a resident is always home at night.
- **Tests are hollow:** they seed `last_changed = start - 3h` (`test_sc_garage_lockout.py:109`), which never happens in HA (Bug Class #40 self-validating fixture).
- **Fix:** drop the setup-time recent-arrival rule. M-2's boot-arrival window (`_arrival_counts` :714-718) already releases on any `→ home` edge in the first 600 s. Alternatively, ignore persons whose `last_changed` is not older than HA start.
- **Classes:** #52-adjacent (restore semantics), #40.

### M1 (MEDIUM): a SLEEP edge before `sleep_start_hour` is released at once by the backstop
- **Where:** `_backstop_delay_s` :318-326.
- **Repro:**
  1. Settings: start 23, end 6, backstop 60.
  2. The operator overrides the house to SLEEP at 22:30. This is legal: the override bypasses the table.
  3. 22:30 is past today's 07:00 deadline, and hour 22 < 23, so the delay is 0.
  4. `_on_backstop` releases right away. Either the engage is dropped (`release_since_intent`) or the lock is followed by an unlock.
  5. Result: no lockout all night.
- The same happens for any SLEEP edge between `end+backstop` and `start` (naps or early bed).
- **Fix:** for a SLEEP_LIKE engage outside the window, schedule tomorrow's deadline whenever `now >= today_deadline`. Keep the 0-delay only for the boot_unknown daytime rebuild, which is deviation (d).
- **Class:** day-boundary-blind time arithmetic (#51 family).

### M2 (MEDIUM, plan-level gap, fail-safe): an interior camera face counts as "arriving"
- **Where:** P2 consumes every `SIGNAL_PERSON_ARRIVING` source (`on_person_arriving` :619-629).
- **The source:** Presence `_handle_face_arrival` (`presence.py:5417-5466`, called from `_handle_camera_change` :5323-5328) fires it for any recognised face on any zone camera.
- **How often:** 60 s debounce per person+zone, and no was-away gate.
- **Effect:** a resident who walks past an interior face camera at 02:00 releases both lockouts. Re-engage follows 15 min later at best.
- **Plan miss:** the plan's P2 row assumed only BLE pre-arrival. The `source` key is available in the payload (`ble` / `geofence` / `camera_face`).
- **Suggested fix:** ignore `camera_face`, or require the person not `home`, or record it as a residual.
- **Class:** #63 (the name "arriving" ≠ a physical arrival).

### L1: excluded or unmapped proximity sensors release with `person=None`
- **Where:** `_on_distance_event` :772-776 and `_person_for_sensor` :739-745.
- **The map:** it only searches `_residents`, which is a setup snapshot minus exclusions.
- **Excluded person's sensor:** it maps to None, which passes the resident check, so the crossing releases.
- **Unmapped person (e.g. un-excluded live, not re-added to `_residents`):** the release also has no `releasing_set` entry, so the re-engage does not wait for them. That is an INV-3 leak: a lock lands at 15 min while they are still at 800 m.
- **Live check:** names match today (`person.ezinne/jaya/oji_udezue/ziri` ↔ `madronehaos_<obj>_distance`).
- **Fix:** map against all `person.*` ids live, then filter by `_is_resident`; return without release if the mapped person is excluded.
- **Class:** #14 snapshot staleness. Deviation (e) is acceptable with this fix.

### L2: `_engage_inflight` is never cleared after a successful lock
- **Where:** popped only on release or on exception (:810, :961).
- **Effect:** harmless today. A later release on an `unlocked` entity sends a redundant unlock.
- **Fix:** clear it when the state is seen `locked`, or at the release read-back.

### L3: DST
- **Where:** `_backstop_delay_s` and `_seconds_until_hour` use `now.replace(hour=…)` on an aware datetime.
- **Effect:** on a DST night the delay is off by 1 h (backstop at 06:00 or 08:00 wall time). Fail-safe early, or 1 h late.
- **Class:** #21/#51.

### L4: deviation (b) means the kiosk is a resident by default
- `person.wall_kiosk` exists live, state `unknown`.
- With an empty exclusion list it is a resident. Its tracker blips are mostly filtered by H3a, but a `not_home → home` flap would release.
- **Operator config-first action:** add it to `security_lockout_excluded_persons` before enabling. The README should say so.

## Deviations judged
| # | Verdict |
|---|---|
| (a) release unlocks while a lock is in flight | ACCEPT. This is how the H-1 race is closed (`_release` :804-810). See L2 hygiene. |
| (b) excluded persons default to empty | ACCEPT with the L4 operator action. |
| (c) any HOME_* releases a VACATION lockout | ACCEPT. HOME_* out of VACATION means someone cleared the override, and release is the safe direction. |
| (d) daytime restart past the backstop releases at once | ACCEPT. Manager restores house state before coordinator setup (`manager.py:481-499`), so a restored VACATION gets reason vacation and has no backstop. |
| (e) proximity mapping by name | ACCEPT once L1 is fixed. Live names match. |
| (f) distance-sensor list needs a reload | ACCEPT. The key is not in the suppress set, so an options change reloads and re-subscribes. |

## Invariant checklist
| Invariant | Result | Evidence |
|---|---|---|
| INV-1 (no new cover writer) | PASS | The regime calls only `lock.lock` / `lock.unlock`. Covers are read for state only (:1001-1003). |
| INV-1B (no remote close) | PASS | No `close_cover` in the diff. |
| Optimizer blocked, layer 1 | PASS | `optimization.py` `_check_safety_denylist`. Runs after the deny-list (not inside it); configured garages first; a raise fails closed. |
| Optimizer blocked, layer 2 | PASS | `security.py` `honor_optimizer_intent` vetoes with `security_owned_cover`. |
| INV-2, Sleep / Vacation / Guest-night / manual / Lock-all | PASS | Release unlocks any `locked` lockout regardless of `reason` (:793-812). |
| INV-2, wake / HOME_* / ARRIVING / backstop | PASS | :565-575 and :1072-1077. |
| INV-2, P1 (incl. M-2 boot cases) | PASS | :698-722. |
| INV-2, P2 | PASS | Fed above the enabled and observation returns. |
| INV-2, P5 incl. the ft→m case | PASS | DistanceConverter. Unknown unit or NaN gives no signal. |
| INV-2, approach zone, hazard, kill switch OFF (`force`), SC disable | PASS | Approach zone :701-703. Hazard is placed above the observation return. SC disable uses the live CM read (`async_release_if_disabled`). |
| INV-2 under SC observation | PASS | Release never reads `observation_mode`. |
| Gap: release suppressed when the kill switch is OFF | as designed | Plan scope. |
| Gap: lockout `unavailable` | named residual | |
| INV-3 | LEAK (LOW) | L1 only. |
| INV-4 | LEAK | H1 (restart), M1 (early SLEEP). Both fail-safe. |
| INV-5 | PASS | Boot window :593-596. Kill switch OFF→ON has no catch-up. |
| INV-6, Away never engages | PASS | `engage_reason` is None for away. Re-engage requires sleep / guest. Guest clock requires `guest`. |
| INV-6, guest-night | PASS | Gated by toggle + window (:581-583, :929-932). |
| Lockouts never in `security_lock_entities` / sweeps | PASS | Separate CONF key. The options validator `lockout_overlap` checks the submitted form (both fields are always submitted). |
| Arming path byte-identical | PASS | `evaluate()` untouched. The feed is inserted before the `try` in `_on_house_state_changed_signal`, in its own try/except. |

## Other checks
- **Sleep hours as floats:** NumberSelector gives floats such as 23.0. The regime does `int(float(...))`, the same truncation as Presence's ctor (`__init__.py:3733-3744`), so both read the same window from one key. PASS.
- **Six reload-suppress keys:** the literals equal the const values. They are in both `OPTIONS_RELOAD_SUPPRESS_KEYS` and `_NO_LIVE_ATTR_KEYS`, and the regime reads them live via `_cfg()` on every event. PASS. The update-listener behaviour belongs to Review B/C.
- **Options round trip:** the four new fields use `_get_current` defaults, and the approach zone uses suggested_value. On an overlap the form re-renders with `errors`. PASS.
- **Presence doc §1/§7 edits:** they match the code (`_arrival_counts`, the proximity crossing, the house-state feed placement). Missing: the `camera_face` source (M2). Add it when M2 is resolved.

## Bug-class tally
#40 ×1, #52-adj ×1, #51/#21 ×2, #63 ×1, #14 ×1, hygiene ×1, config-first ×1.
