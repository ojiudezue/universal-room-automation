# AUDIT — Fan-interference recheck bug hunt (read-only trace)

**Date:** 2026-08-18
**Scope:** `domain_coordinators/presence_fan_recheck.py` `FanRecheckManager`, its
per-tick driver in `domain_coordinators/presence.py`, the room-coordinator
occupancy-source production it depends on (`coordinator.py`), and the cycle
test suite.
**Method:** line-by-line trace of the whole recheck lifecycle
`idle → armed → paused → (vacated|confirmed) → cooldown → idle`, cross-checked
against the producers of every value the eligibility gate reads. No code
changed. Every claim carries a `file:line`. Where a branch's live behavior
cannot be proven statically it is marked **SUSPECTED — needs live signal** and
the discriminating observation is named.

---

## TL;DR verdict

- The recheck **state machine itself is sound and its downstream actuation
  exists and is correct** — `apply_fan_recheck_release` is implemented and
  clears occupancy properly (`coordinator.py:4578-4609`). So "the release is a
  no-op / missing method" is **ruled out**.
- The failure is **upstream of arming**: for Study A the reported live state was
  `fan_recheck_state=idle`, `fan_recheck_last_attempt_iso=null`. Both together
  prove the room **never armed** — arming sets `state=ARMED`
  (`presence_fan_recheck.py:516`) and every terminal path out of ARMED stamps
  `last_attempt_at` (`:550/:566/:623/:834`). A null `last_attempt` with `idle`
  means `_is_eligible` returned `False` on every tick (or the driver never
  reached it).
- **Yet the documented 9-condition eligibility gate returns `True` for the state
  the operator described** (mmwave-sole, fan on, generic room, not sleep, no
  persons anywhere). See the Study-A walk-through below. Therefore the live
  blocker is an **undocumented production gate**, and there are two
  high-confidence candidates plus one confirmed reason the bug survived to
  production undetected.

**Ranked findings:**

| # | Finding | Confidence | Kind |
|---|---|---|---|
| A | Hollow test coverage — the entire suite drives a `_FakeRoomCoord` with hand-fed `occupancy_source="mmwave"`; the real occupancy-source production + ring append are never exercised. This is *why* "never worked" ships green. | **CONFIRMED** | Test-authority defect |
| B | D2 mmwave-fan-demotion **precedence starvation** — D2 (on by default) flips `occupied=False` for exactly the fan-ghosted rooms the recheck targets, and its "defer to recheck" guard only fires once the recheck is *already* non-idle, which it can never become. Recheck hits `not_occupied` and never arms. | **SUSPECTED (high)** | Cross-mechanism precedence bug |
| C | Ring/eligibility is fed by an event-driven room-refresh cadence decoupled from the 60 s recheck tick; eligibility reads the RING while the arm-recheck reads LIVE source — inconsistent, and non-`mmwave` values (`timeout`, D2) interleave into the ring, failing condition-2. | **SUSPECTED (med)** | Two-clock / logic inconsistency |
| D | The whole per-room driver loop shares ONE `except → DEBUG` (`presence.py:6904`); a single room raising inside `on_room_tick` silently aborts evaluation for every room after it that tick. | **CONFIRMED (fragility)** | Swallowed-exception blast radius |

---

## 1. Lifecycle facts established (so they can stop being re-litigated)

- **Manager is built and set up unconditionally** at PresenceCoordinator setup:
  `presence.py:2733-2734` constructs `FanRecheckManager` and awaits
  `async_setup()` inside a try that nulls the manager only on failure
  (`:2740`). `async_setup` sets `_setup_done=True` (`presence_fan_recheck.py:197`).
- **Driver runs every 60 s for every ROOM entry.** `_periodic_inference`
  (`presence.py:4687`) is wired via `async_track_time_interval(..., 60 s)`
  (`presence.py:2688-2692`) and calls `_run_inference("periodic")` (`:4695`).
  `_run_inference` has **no early return** at method-body indent between its
  start (`:5344`) and the recheck block (`:6893`) — verified by grep. The block
  iterates all `ENTRY_TYPE_ROOM` entries and calls
  `on_room_tick(room_coord)` (`presence.py:6893-6903`). So a *stable* stuck room
  IS visited every 60 s — "event-driven, never ticks" is **ruled out** for the
  driver.
- **The vacate actuation exists and is correct.**
  `_on_pause_window_done → _restore` (`presence_fan_recheck.py:660-742`) calls
  `room_coord.apply_fan_recheck_release()` (`:694`), which sets
  `STATE_OCCUPIED=False`, source `fan_recheck_release`, clears
  `_last_motion_time`/`_became_occupied_time` and `_last_occupied_state=False`
  (`coordinator.py:4590-4603`). Delegation targets `pause_for_recheck` /
  `restore_after_recheck` / `snapshot_room_fan` all exist on the FanController
  (`hvac_fans.py:1815/1841/1883`). So *if the machine reaches the pause window
  with the room empty, it vacates correctly.*

---

## 2. Finding A (CONFIRMED) — the tests never exercise the production trigger

Every test in `quality/tests/test_fan_recheck_mode2_cycle.py` drives a
hand-built `_FakeRoomCoord` (`:224-250`) whose `data` is literally
`{"occupied": True, "occupancy_source": "mmwave", "motion_detected": False,
"presence_detected": True}` (`:233-238`) and whose `recent_occupancy_sources()`
returns a caller-supplied list (`:241-242`). The eligibility path is therefore
validated **only against inputs the test itself asserts are correct**.

The real trigger surface — how `coordinator.py` decides
`data[STATE_OCCUPANCY_SOURCE]` (`coordinator.py:3058-3107`, `3143`, `3257`,
`3337`, `3452`) and how the `_recent_occupancy_sources` ring is filled
(`coordinator.py:4548-4550`) — is **never driven by any test**. This is the
"hollow test anchor" / fake-coordinator class from institutional memory
(`v5.8.0` setup-recursion incident used the same fake-coordinator pattern and
shipped a crash). It is the mechanism by which a feature that "never worked"
live can pass its full suite: the suite proves the state machine's *internal*
transitions, not its *production* eligibility. **This is the reason the bug was
invisible**, and it is directly fixable (a test that drives a real
`UniversalRoomCoordinator` occupancy tick into `on_room_tick`).

---

## 3. Finding B (SUSPECTED, high) — D2 demotion starves the recheck of `occupied`

The room-tier coordinator carries a **second, competing** fan-ghost mechanism:
D2 "mmwave-fan-demotion" (`coordinator.py:3328-3455`). It is **enabled by
default** — `MMWAVE_FAN_CORROBORATION_ENABLED = True` (`const.py:805`) and
`D2_PIR_STALENESS_MULTIPLIER = 2` (`const.py:586`). When its bar is met
(occupied, mmwave-sole source, PIR stale ≥ 2× timeout, room flagged
`is_room_mmwave_fan_demoted`, no BLE/camera) it does:

```
coordinator.py:3451  data[STATE_OCCUPIED] = False
coordinator.py:3452  data[STATE_OCCUPANCY_SOURCE] = OCCUPANCY_SOURCE_MMWAVE_FAN_DEMOTED
```

D2 targets **exactly the population the recheck targets**: a fan-ghosted,
mmwave-sole, PIR-stale occupied room. D2 has a "defer to the recheck" guard:

```
coordinator.py:3370-3402
  _state = fr_mgr.get_room_state(room_name)
  if _state and _state != "idle":  recheck_in_flight = True
  ...
  if not recheck_in_flight:   # only THEN does D2 demote
```

**The precedence is inverted for a cold start.** The recheck can only leave
`idle` by first observing `data["occupied"] is True` **and** mmwave-sole
(`presence_fan_recheck.py:377-394`). But on the tick D2's bar is met, D2 runs
inside the *same* room `_async_update_data` and sets `occupied=False`
*before* the recheck's next 60 s tick reads it. The recheck then hits:

```
presence_fan_recheck.py:378-379
  if not data.get("occupied"):
      return self._veto(room_name, "not_occupied")
```

so it stays `idle`; D2's `recheck_in_flight` guard therefore stays `False`
forever; D2 keeps demoting. **Chicken-and-egg: D2's deferral only helps a
recheck that already armed, but D2 prevents it from ever arming.** For any room
whose fan-ghost is steady enough to satisfy D2's (stricter, PIR-stale-2×) bar,
the recheck is structurally starved — which reads exactly as "it never works."

- **Why SUSPECTED not CONFIRMED:** D2's bar is *stricter* than the recheck's, so
  rooms whose ghost is milder than 2× PIR-staleness would still be
  recheck-eligible; and the 08-13 `occupied_confirmed` proves the recheck armed
  at least once historically (so it is situational, not universal). Confirming B
  for Study A requires the live veto reason.
- **Discriminator:** read `sensor.<study_a>_fan_recheck_state` attribute
  `fan_recheck_veto_counts`. A dominant **`not_occupied`** count with
  `fan_recheck_eval_count > 0` confirms B (the room is being demoted out from
  under the recheck). Cross-check the live `occupancy_source` — if it reads
  `mmwave_fan_demoted` while the operator believes the room is "mmwave-sole
  occupied," B is confirmed.

---

## 4. Finding C (SUSPECTED, med) — ring cadence + ring-vs-live source split

Condition-2 requires the **ring** to show `mmwave` for the last N ticks
(`presence_fan_recheck.py:388-394`, N default 3 —
`const.py:761`). The ring is appended once per **room** `_async_update_data`
(`coordinator.py:4548-4550`) — an **event-driven** cadence (sensor state
changes), decoupled from the **60 s periodic presence tick** that reads it.
Two consequences:

1. **Interleaved non-`mmwave` values fail condition-2.** The source recorded
   into the ring is `timeout` whenever the mmWave sensor is momentarily off but
   the room is still inside `_occupancy_timeout` (`coordinator.py:3092`), and
   `mmwave_fan_demoted` when D2 fires (`:3452`). Any such value inside the last
   3 ring slots trips `not_mmwave_sole` (`presence_fan_recheck.py:393-394`).
   Intermittent mmWave (common) → the ring rarely holds 3 clean consecutive
   `mmwave` → `not_mmwave_sole` / `mmwave_history_short` veto indefinitely.
2. **Eligibility reads the RING, the arm-recheck reads LIVE.** `_is_eligible`
   uses `recent_occupancy_sources()` (`:389`) but `_still_armed_eligible`
   (60 s later, immediately before pausing) requires the **live**
   `data["occupancy_source"] == "mmwave"` *exactly* (`:860`). A room that armed
   off a clean ring can be denied the pause because the live source drifted to
   `timeout` during the arm delay — producing an `arm_expired_ineligible`
   cancel + 1800 s cooldown (`:565-578`, cooldown default `const.py:661`) and no
   pause. This is an internal inconsistency, not a fatal gate, but it depresses
   the pause rate and would make the feature *feel* dead even when it arms.

- **Discriminator:** `fan_recheck_veto_counts` dominated by
  `not_mmwave_sole` / `mmwave_history_short` confirms C at the eligibility
  stage; a nonzero cooldown population with `arm_expired_ineligible` activity-log
  rows confirms the arm-drop half.

---

## 5. Finding D (CONFIRMED fragility) — one swallowed try wraps the whole loop

```
presence.py:6893   if self._fan_recheck_manager is not None:
presence.py:6894       try:
presence.py:6895           for entry in ...async_entries(DOMAIN):
presence.py:6903               self._fan_recheck_manager.on_room_tick(room_coord)
presence.py:6904       except Exception:  # -> _LOGGER.debug(...)
```

The `for` loop over all rooms sits inside a **single** `try` that swallows to
`DEBUG`. `on_room_tick` (`presence_fan_recheck.py:239-271`) has **no internal
per-room guard**. If `on_room_tick` raises for one room, the loop aborts and
**every room enumerated after it is skipped that tick**, invisibly at default
log level. Most calls inside `_is_eligible` are individually guarded, so I could
not prove a *deterministic* raise from static reading — hence "fragility" not
"root cause." But it is a real blast-radius defect: it means a single
misbehaving room can silently suppress the recheck for Study A if Study A is
later in entry order, and it hides the evidence at DEBUG. If B/C are excluded by
the veto counts, D is the next thing to chase (raise the log to DEBUG for
`custom_components.universal_room_automation.domain_coordinators.presence` and
watch for "per-tick fan-out failed").

---

## 6. Study A, tonight — step through `_is_eligible` for the described state

State per the brief: mmwave-sole, fan on, generic (non-bedroom/media) room, not
sleep, no persons anywhere.

| Line | Gate | Result for Study A |
|---|---|---|
| `:350-351` | master switch | pass (assumed enabled; default `False` `const.py:623`, so verify) |
| `:352-355` | per-room enable | pass (default `True` `const.py:629`) |
| `:357-358` | fan control off | pass |
| `:373-375` | sleep gate | pass (not sleep) |
| `:378-379` | **`not occupied`** | **pass IF live `occupied` is True — the crux; D2 can make this False (Finding B)** |
| `:391-394` | ring 3× mmwave | pass IF ring clean (Finding C can fail this) |
| `:397-404` | fan configured + on | pass (fan on) |
| `:407-408` | boot settle | pass (`_boot_settle_done` flips True, `presence.py:2178/2180/2263`) |
| `:413-414` | manual-off cooldown | pass (assumed) |
| `:423-427` | rate cap | pass |
| `:430-440` | person coord + L1 | pass (no persons → `l1_persons` empty) |
| `:452-469` | Tier-1 zone-L3 | **returns True** if `zone_persons` empty (no persons) |
| `:482-504` | Tier-0/2 path | **returns True** (no L2-adjacent, generic room, `trust_sensors` default True) |

**Conclusion:** with the state exactly as described, `_is_eligible` returns
`True` (at `:469` or `:504`) and the room should arm within one 60 s tick. Since
it demonstrably did not, **at least one of the "assumed pass" gates is actually
failing in production** — and the two that depend on values the operator cannot
see directly are `occupied` (Finding B: D2 demotion) and the ring
(Finding C). That is the whole ballgame. The single cheapest disambiguation is
already built: enable `sensor.<study_a>_fan_recheck_state` (it is
`_attr_entity_registry_enabled_default = False`, `sensor.py:15953`) and read
`fan_recheck_eval_count` + `fan_recheck_veto_counts` (`presence_fan_recheck.py:
290-314`, exposed `sensor.py:15966-16002`):

- `eval_count == 0` → driver never reached `_is_eligible` → Finding D (or manager
  is None; check the WARNING at `presence.py:2736`).
- `eval_count > 0`, veto dominated by `not_occupied` → **Finding B**.
- veto dominated by `not_mmwave_sole` / `mmwave_history_short` → **Finding C**.
- veto dominated by anything else (`no_fan_on`, `rate_cap`, `manual_off_cooldown`,
  `sleep_state`, `master_off`) → a plain config/state gate the "textbook
  eligible" assessment missed.

This observation set *discriminates* the candidates (per the acceptance-criteria
rule) — each hypothesis predicts a different dominant veto string.

---

## 7. Has the recheck ever vacated a room?

**Not provable statically, and no evidence it has.** The 2026-08-13
`occupied_confirmed` (per the prior agent) proves the machine *armed + paused +
concluded* at least once — i.e. the `idle→armed→paused→_on_pause_window_done`
spine has executed — so a blanket "the driver never runs" is false. But
`occupied_confirmed` is the **non-vacate** outcome (`OUTCOME_OCCUPIED_CONFIRMED`,
`presence_fan_recheck.py:664`): it means the pause ran and mmwave *stayed*, so
`apply_fan_recheck_release` was **not** called (`:688` guards on
`outcome == OUTCOME_VACATED`). I found no evidence any `vacated` outcome or any
`apply_fan_recheck_release` invocation has occurred. The release path is
correctly implemented (§1) and would work if reached; whether it ever *has* must
be answered from the recorder / `ura_activity_log` (`fan_recheck_outcome` rows
with `details_json.outcome == 'vacated'`, and the room log line "fan-recheck
released occupancy", `coordinator.py:4605`). **Recommend that DB read as the
confirming step** — a zero count there is the definitive "it has never actually
vacated."

---

## 8. What to do next (not built — read-only audit)

1. **Read the live veto counts** for Study A (and 2-3 other textbook rooms) to
   pick between B / C / D per §6. This is a 2-minute live read and collapses the
   candidate set.
2. **Read `ura_activity_log`** for any `fan_recheck_outcome` `vacated` row ever
   (§7). Establishes whether the vacate path has *ever* fired.
3. If **B**: the fix is a precedence/ordering change — D2 must not demote a room
   the recheck *could* arm (e.g. D2 yields when the room is recheck-*eligible*,
   not only when recheck is already in-flight), or the recheck must read a
   pre-D2 occupancy snapshot. This is a cross-coordinator (room ↔ presence)
   change → Tier 2-DB / regression-prone.
4. If **C**: unify the source-of-truth — eligibility and `_still_armed_eligible`
   should read the same signal, and condition-2 should tolerate the documented
   fan-ghost source set rather than requiring a strict 3× `mmwave` run.
5. Independent of root cause: **kill Finding A** — add a test that drives a real
   `UniversalRoomCoordinator` occupancy tick (mmWave on, no motion, fan on)
   through `on_room_tick` and asserts an arm, so the production trigger surface
   is actually covered.
6. Independent of root cause: tighten Finding D — per-room `try` inside the loop
   so one room's raise cannot silently skip the rest, and log at WARNING.

---

*Read-only audit. No source files were modified. All line numbers are against
the working tree at commit-time on `develop`.*
