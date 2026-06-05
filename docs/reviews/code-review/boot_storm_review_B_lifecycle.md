# Boot-storm settle gate — Reviewer B (lifecycle / async / race conditions)

**Branch:** `feature/boot-storm-settle-gate`
**Commit:** `2d9577a` (includes Reviewer A fix-up: HIGH-A1, HIGH-A2, MED-A3, MED-A4)
**Framing:** async / lifecycle / race conditions / restart resilience / HA-lifecycle / timer & listener cleanup.
**Out of scope:** general correctness / edge cases (Reviewer A; do not re-litigate).
**Reviewer:** Reviewer B (ura-reviewer agent), 2026-06-04.

---

## Verdict

**FIX-FIRST.** No CRITICAL on the lifecycle axis. One **HIGH (B-H1)** on the re-kick path that materially worsens the bug Reviewer A claimed to close — the post-release `_async_decision_cycle` task can fire AFTER `async_teardown` if a reload races with the timeout/HA-started callback (the v4.7.18.1 deploy-restart memory in `MEMORY.md` shows this isn't theoretical). Two **MEDIUM** items on listener-tracking edge cases and one MEDIUM on a missing re-entrancy interaction with the existing 5-min periodic tick. Several LOWs on observability and idiom drift.

Lifecycle "is the gate cleanly cancellable on reload / does it leak listeners / does it use-after-free `self.hass`" — mostly **yes, with one gap.** The use of `_unsub_listeners` for both Predicate B paths is correct; `_cancel_listeners()` covers both Gate-1 and Gate-2 unsubs symmetrically. The new re-kick block uses the established `_pending_tasks` discipline, which Reviewer A foreshadowed I would want, and which is correct in steady-state. The HIGH is a narrow window during the very lifecycle event that motivated the original `MEMORY.md` warning.

---

## Summary stats

| Severity | Found | Fix in this cycle | Defer |
|----------|-------|-------------------|-------|
| CRITICAL | 0 | — | — |
| HIGH | 1 | 1 | 0 |
| MEDIUM | 3 | 2 | 1 |
| LOW | 4 | 2 | 2 |

Per the `Fix LOWs In-Cycle` operator rule (`MEMORY.md`), I am routing reasonable LOWs into the fix-up pass and explicitly deferring the others with reasons.

---

## Findings

### HIGH-B1 — Re-kick task can fire after `async_teardown()` clears `_pending_tasks`

**File:** `custom_components/universal_room_automation/domain_coordinators/hvac.py:733-739` (re-kick block in `_release_boot_settle`); interaction with `async_teardown` at `hvac.py:2127-2145`.
**Bug class:** **#34-adjacent (callback-after-teardown)** + **#19 (Untracked Background Tasks)** at the boundary. Not a clean #34 because the import is correct; the lifecycle race is the harm.

**Race window.** Two paths into `_release_boot_settle("ha_started")` / `("timeout")` are synchronous `@callback`s fired by HA's bus / scheduler on the event loop. When either fires:

1. Guard at `:711` is checked: `if self._boot_settle_done: return`.
2. Flag flip at `:713`: `self._boot_settle_done = True`. (No `await` between the check and flip — atomicity on a single-threaded loop is OK.)
3. New re-kick at `:733-739`:
   ```python
   if self._boot_settle_hvac_suppressed > 0:
       task = self.hass.async_create_task(
           self._async_decision_cycle(),
           name="hvac_post_boot_settle_kickoff",
       )
       self._pending_tasks.add(task)
       task.add_done_callback(self._pending_tasks.discard)
   ```

The race: `async_teardown()` at `:2137-2139` does:
```python
for task in list(self._pending_tasks):
    task.cancel()
self._pending_tasks.clear()
```
Then `_cancel_listeners()` at `:2145` unsubs the timeout and HA-started listeners.

**Problem:** `async_teardown` is an async coroutine. There is a window between
(a) the loop dispatching the timeout `@callback` (which is sync — runs to completion before teardown can resume), and
(b) `async_teardown` actually entering the `for task in list(...)` loop.

Concretely: imagine the parent-entry-reload path documented in `MEMORY.md` ("Parent-entry reload watchdog hazard"). HA marks the entry for unload → schedules `async_teardown` → the loop is still dispatching pending sync callbacks BEFORE that coroutine runs. If the failsafe timeout's `_timeout_release_boot_settle` callback is in the pending queue, it fires:
- Flips `_boot_settle_done`.
- Spawns the kickoff task via `async_create_task` and adds it to `_pending_tasks`.
- Returns.

`async_teardown` then runs, iterates `_pending_tasks`, cancels the kickoff (good). But there is a second variant that's worse:

If the timeout was already cancelled by `_cancel_listeners` in a PREVIOUS reload but the coordinator is later re-instantiated (`_boot_settle_done = False` again per `__init__`) and a NEW timeout fires while a second reload is in flight, the kickoff task can be spawned against a `self.hass` that is **still valid** (HA `hass` outlives entries) but against an internal coordinator state (`_zone_manager`, `_egress_manager`, `_decision_timer_unsub`) that was torn down. The kickoff calls `await self._run_decision_cycle()` which reads `self._zone_manager`, `self._preset_manager`, etc. — and if these were nulled or replaced mid-teardown, we get either a stale-state actuation or an `AttributeError` deep in the decision cycle.

I did not verify the exact sequence by reading the parent-entry reload path in `__init__.py` — flagging this as the worst-case lifecycle risk consistent with the documented `parent reload watchdog` incident. **Mark explicitly as "asserting under uncertainty"** per the No-Fabrication rule.

**Why the existing guard isn't enough.** The early `if self._boot_settle_done: return` guard idempotency-protects re-entry into `_release_boot_settle` itself, but does NOT protect against the task it spawned outliving the coordinator. `add_done_callback(self._pending_tasks.discard)` runs even after `clear()`; calling `.discard()` on an empty set is harmless, so no second exception — but the task body has already executed against a torn-down coordinator.

**Concrete fix.** Guard the re-kick on still-alive state and prefer enqueueing the cycle on the *next* loop iteration via the existing lock-aware periodic path rather than creating a fire-and-forget task from inside a sync `@callback`. Two options, ranked:

1. **(preferred) Defer to the next periodic tick boundary** by storing a one-shot pending flag and letting `_async_decision_cycle` consume it on its next tick. The cost is up to 5 min latency (the original HIGH-A2 hole), but you can shrink it by chaining a short `async_call_later(self.hass, 1, self._async_decision_cycle)` from the release path and storing the unsub in `_unsub_listeners` so it is cancelled by `_cancel_listeners` exactly the same way the timeout itself was. This keeps the entire release path inside the listener-cleanup envelope.

2. **(if option 1 is too heavy)** Wrap the re-kick in a teardown-aware guard. Add `_is_torn_down: bool` set to True at the very top of `async_teardown` BEFORE the `_pending_tasks` cancel loop. The re-kick block checks `if self._is_torn_down: return` immediately after the gate-flip and BEFORE creating the task. The body of `_async_decision_cycle` should also check `if self._is_torn_down: return` at its top so even a task that slipped through the gap aborts before touching `_zone_manager`.

I lean option 1: it reuses the existing `_unsub_listeners` cancellation symmetry that the rest of this cycle is built around, instead of introducing a parallel `_is_torn_down` flag that downstream code has to remember to consult.

---

### MED-B2 — `async_listen_once` unsub remains in `_unsub_listeners` after the event fires, so `_cancel_listeners()` calls a stale handle

**File:** `presence.py:1741`, `hvac.py:403`.
**Bug class:** #19 / #38 adjacency — not a leak exactly (the listener already auto-removed itself), but a stale-handle pattern.

`bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, handler)` returns an unsub callable whose listener is auto-removed when the event fires (per HA dev docs — **I did not verify in HA source this session, flagging as inferred**). The unsub is stored in `_unsub_listeners` (presence.py:1741, hvac.py:403). On a normal cold boot the event fires → handler runs → listener auto-removes → unsub becomes stale. On teardown, `_cancel_listeners()` (base.py:282-286) calls the stale unsub. **Per my reading of HA dev docs and prior URA usage** (e.g. presence.py:5172 wraps a similar unsub in `try/except`), this is normally a no-op and safe. But the pattern in this cycle does NOT wrap the call in try/except, and the entire `_cancel_listeners` loop will raise on the first stale unsub that does NOT swallow KeyError gracefully — silently skipping every subsequent unsub in the list.

This is a latent fragility, not a fired bug. The fix is small and worth doing in-cycle:

**Concrete fix.** Either:
- Wrap `_cancel_listeners` in per-unsub try/except (one-line change at base.py:284-286), OR
- Have `_on_ha_started_release_boot_settle` and `_timeout_release_boot_settle` self-remove their unsub from `_unsub_listeners` when fired:
  ```python
  @callback
  def _on_ha_started_release_boot_settle(self, _event: Any) -> None:
      self._release_boot_settle("ha_started")
      # listener auto-removed by HA; drop the now-stale unsub so a future
      # _cancel_listeners() doesn't call into stale state.
      try:
          self._unsub_listeners.remove(self._unsub_ha_started_handle)
      except (ValueError, AttributeError):
          pass
  ```
  This requires storing the unsub on `self` (presently they are local `_unsub_ha_started` / `_unsub_started` / `_unsub_to`).

Option A (wrap `_cancel_listeners`) is the smaller-blast-radius fix and applies to every coordinator, not just this cycle.

---

### MED-B3 — `hass.is_running` read at `async_setup` is racy on the genuine reload path

**File:** `presence.py:1717-1727`, `hvac.py:380-390`.
**Bug class:** #20 (Concurrent Config Entry Reload Race) — the gate-scoping decision is read once and cached as a side effect of which init path runs.

`getattr(self.hass, "is_running", False)` is read exactly once during `async_setup`. The flag means "HA core has reached the RUNNING state." There is a window where:

- HA is in `STARTING` (`is_running == False` per HA core convention; — **inferred from `MEMORY.md` notes on lifecycle, not re-verified in HA source this session**), URA `async_setup_entry` runs, `is_running` is False → the boot-settle gate is armed.
- A few hundred ms later, HA transitions to `RUNNING`, fires `EVENT_HOMEASSISTANT_STARTED` → our listener fires → gate releases. **Correct path.**

But:

- An options-flow reload during a fresh boot (rare but possible) calls `async_unload` then `async_setup` of the entry AFTER HA is `RUNNING`. Here `is_running == True` is seen at setup time → gate is born already-released with reason `"not_cold_boot"`. **Correct.**

- The third path: a reload during `STARTING` (e.g., a config validation error mid-boot triggers an entry retry). `is_running` is False at the moment we read it → gate is armed. But HA may flip to `RUNNING` *between* our `getattr` read and our `async_listen_once` registration. That window is small but real, and the registration of `async_listen_once(EVENT_HOMEASSISTANT_STARTED)` AFTER the event has already fired means our listener never fires for that boot. The failsafe timeout (60s) is the only release path in that case. **Functionally correct (failsafe catches it) but the failure mode is silent — we suppress for up to 60s for no reason on an already-running HA.**

**Concrete fix.** After registering the `async_listen_once` listener, do a second `is_running` check; if True, immediately call `self._release_boot_settle("ha_already_running_at_listen")` to short-circuit the failsafe wait. This double-check pattern is standard for `async_listen_once(EVENT_HOMEASSISTANT_STARTED)` — HA's own docs example for "wait until started" uses it.

---

### MED-B4 — Periodic 5-min `_async_decision_cycle` tick can race with the post-release re-kick

**File:** `hvac.py:609-616` (periodic timer setup) + `:733-739` (re-kick block) + `:777-781` (re-entrancy guard).
**Bug class:** lock-discipline / re-entrancy.

The periodic timer at `hvac.py:609` calls `self._async_decision_cycle` every 5 minutes. The re-kick at `:734-735` calls `self._async_decision_cycle` as a `hass.async_create_task` from inside a sync `@callback`. Both eventually enter `_async_decision_cycle`. The re-entrancy guard at `:778-779` is:

```python
if self._decision_cycle_lock.locked():
    return
async with self._decision_cycle_lock:
    await self._run_decision_cycle()
```

This is correct for the steady-state case. But:

1. The post-release re-kick `await self._run_decision_cycle()` can take seconds (real I/O — `climate.set_temperature` round-trips). If the 5-min periodic timer fires *during* the re-kick, the periodic call sees `lock.locked() == True` and returns silently. **No problem on this tick** — but the next periodic tick after that will be 5 min later. If the re-kick *failed mid-flight* (raised), there is no retry until the next periodic tick. **5-min lag hole, same shape as the original HIGH-A2 hole Reviewer A claimed to close** — only shifted by one tick.

2. Worse: there is no logging that the periodic tick was skipped because of `lock.locked()`. A silent skip is hard to debug.

**Concrete fix.** Add a single DEBUG log line at `hvac.py:779` ("decision cycle already in flight — skipping periodic tick") so the operator can see the overlap pattern post-deploy. Don't change the semantics — silent skip is correct, but it should be observable in the system log when investigating a "why didn't it actuate?" incident.

(I am not flagging the kickoff-vs-periodic ordering as a CRITICAL because the lock is the right primitive and the failure mode is one-tick lag, not corruption.)

---

### LOW-B5 — `_decision_timer_unsub` lives outside `_unsub_listeners` — divergent cleanup discipline

**File:** `hvac.py:185` (init), `:609` (assign), `:2132-2134` (cancel).
**Bug class:** #38-adjacent (the same shape that motivated tracking listener unsubs uniformly).

`_decision_timer_unsub` is the 5-min periodic timer. It's tracked as a separate attribute, not in `_unsub_listeners`. Cleanup at `hvac.py:2132-2134` is correct, but the divergence means every reviewer of every cycle has to remember "is this unsub tracked centrally, or does it have a bespoke teardown path?". The new cycle correctly put the Gate-2 unsubs into `_unsub_listeners`, which is the right pattern — but the periodic timer is still the odd one out.

**Defer to a future cleanup cycle.** Not worth a fix-up in this cycle (it's pre-existing and the new code is fine). Flagging for a possible separate hygiene cycle that consolidates all per-coordinator timers into `_unsub_listeners`.

---

### LOW-B6 — Defensive `try/except Exception` around `getattr(self.hass, "is_running", False)` is excessive

**File:** `presence.py:1717-1720`, `hvac.py:380-383`.
**Bug class:** defensive-code drift.

`getattr(obj, attr, default)` cannot raise on a missing attribute — that's its contract. Wrapping it in `try/except Exception` is dead defense and adds two lines of noise per call site. The comment "defensive against stub hass" is misleading — a stub `hass` will either return False (via the `getattr` default) or return whatever the stub provides. Neither raises.

**Concrete fix.** Drop the try/except. Replace with a bare `_ha_running = bool(getattr(self.hass, "is_running", False))`. Saves 4 lines × 2 sites = 8 lines of noise.

---

### LOW-B7 — `_boot_settle_started_utc` is set on presence but NOT on hvac

**File:** `presence.py:1729` (set) vs `hvac.py:380-421` (absent).
**Bug class:** instrumentation asymmetry.

Presence records the gate-start time for diagnostic purposes; HVAC does not. The asymmetry shows up if the operator wants to compute "how long was Gate 2 actually suppressing?" — the answer is "we don't know, only the suppressed-cycle count." If Gate 1 fires the timeout but Gate 2 doesn't (because Gate 2 was released by `ha_started` 30s earlier), the operator can't tell from the sensor which gate caught the storm and which was redundant — which the code comment at `sensor.py:3862-3864` says is the whole point of having two counters.

**Concrete fix.** Mirror the presence pattern: add `self._boot_settle_started_utc = dt_util.utcnow()` at `hvac.py:392` (inside the else branch) and surface it on the sensor as `boot_settle_hvac_armed_at_utc` alongside the existing `boot_settle_hvac_suppressed`.

**Defer if scope-pressured** — the existing counters are sufficient for the "redundant gate pruning" decision the operator wants to make. Treating this as a LOW + defer is reasonable.

---

### LOW-B8 — `async_listen_once` and `async_call_later` cleanup paths use distinct local-variable names across the two coordinators

**File:** `presence.py:1737/1752` (`_unsub_ha_started`, `_unsub_timeout`) vs `hvac.py:399/411` (`_unsub_started`, `_unsub_to`).
**Bug class:** idiom drift / readability.

Minor. The two coordinators implement the same pattern but with slightly different local-variable names (`_unsub_ha_started` vs `_unsub_started`, `_unsub_timeout` vs `_unsub_to`). The next person to grep "boot-settle listener" has to look in both places under different names.

**Concrete fix.** Pick one set of names (the presence names are more self-documenting) and rename in hvac.py. 4 lines.

---

## Per-axis answers to the prompt's six lifecycle/async risk questions

1. **Listener/timer cleanup symmetry.** ✅ for both unsubs being stored in `_unsub_listeners` (presence.py:1741/1757, hvac.py:403/416) and ✅ for `_cancel_listeners` covering them on teardown (base.py:282-286, called from presence.py:5180 and hvac.py:2145). ⚠️ for the stale-handle pattern after the event auto-removes the listener (MED-B2). No double-unsub risk on the cold path because `async_listen_once`'s unsub is idempotent-no-op post-fire per HA dev docs (inferred, not source-verified this session).

2. **Re-kick task safety (HIGH-A2 fix).** ⚠️ The new block at `hvac.py:733-739` is mostly correct: it does track via `_pending_tasks` and `add_done_callback(self._pending_tasks.discard)` is the right pattern. But it can fire after `async_teardown` cancels other pending tasks on a parent-entry reload race (**HIGH-B1**). `async_create_task` from a sync `@callback` context IS safe (the loop is running by definition when a callback fires) — this part is fine. Re-entrancy with the periodic tick is governed by `_decision_cycle_lock` and the 5-min lag hole is technically still possible if the re-kick fails (MED-B4).

3. **Idempotency / races.** ✅ The `if self._boot_settle_done: return` early-exit guard at `_release_boot_settle:1669/711` is correct on a single-threaded event loop. Flag-flip + re-kick are atomic on the loop. The timeout-vs-HA-started race is correctly resolved by whichever fires first — the second is a no-op. ⚠️ Note: when both gates exist (presence + HVAC), they're INDEPENDENT — presence may release via "real_input" while HVAC's timeout independently fires. That's deliberate and matches the planning doc, but the operator should know the sensor attrs reflect the per-gate state, not a unified state.

4. **Cold-boot-vs-reload scoping race.** ⚠️ See MED-B3 — there is a small window where `is_running` is False at read-time but True before the listener registers, and the failsafe timeout becomes the only release path (60s of pointless suppression). Fix is a post-registration double-check.

5. **Restart resilience.** ✅ No persistence — `__init__` re-initializes `_boot_settle_done = False` every time a coordinator is instantiated. The `MEMORY.md` entry for v4.7.18.1 ("HouseStateMachine does NOT persist across restart") is the same property here, and that's by design. The failsafe timeout at 60s is the guaranteed-release backstop on every lifecycle path I traced. ⚠️ The one variant I could not rule out by reading source this session: if `async_setup` raises mid-init before either listener registers but AFTER `_boot_settle_done = False` is set by `__init__`, the coordinator may be in a hung-armed state with no release path. But HA's setup-retry path will tear the coordinator down and re-instantiate, so this is bounded.

6. **Interaction with existing scheduler discipline.** ✅ The re-kick uses `_pending_tasks` + `add_done_callback(self._pending_tasks.discard)` which mirrors hvac.py:1397-1398 / 1471-1472 / 1489-1490 / 1762-1763. The `_decision_cycle_lock` is consulted at `:778-779`. No bypass of existing guards. ⚠️ MED-B4 notes the silent-skip-on-overlap visibility gap, but the lock is the right primitive.

---

## Fix-up routing

**Apply in this cycle (per `Fix LOWs In-Cycle`):**
- HIGH-B1 (post-teardown re-kick guard — option 1 preferred)
- MED-B2 (wrap `_cancel_listeners` in per-unsub try/except — 3 LoC change in base.py)
- MED-B3 (post-listen-registration double-check on `is_running`)
- LOW-B6 (drop redundant try/except around `getattr` — 8 LoC trim)
- LOW-B8 (rename hvac.py local vars for consistency — 4 LoC)

**Defer with reasons:**
- MED-B4 (silent-skip log) — strictly observability; can ship as a separate small hygiene commit if the operator wants. Not blocking.
- LOW-B5 (periodic timer unsub consolidation) — pre-existing pattern, separate hygiene cycle.
- LOW-B7 (hvac armed-at timestamp) — counters are sufficient for the "prune redundant gate" decision.

---

## Lifecycle reachability table (Gate 2, cold boot)

| Release path | Cleanup site | Stale-handle risk after fire | Teardown-coverage |
|---|---|---|---|
| Predicate B path 1 — `EVENT_HOMEASSISTANT_STARTED` listener | `_unsub_listeners` (hvac.py:403) → `_cancel_listeners` (hvac.py:2145) | MED-B2 (stale no-op via HA's listener auto-remove; inferred from dev docs) | ✅ |
| Predicate B path 2 — `async_call_later(60s)` timer | `_unsub_listeners` (hvac.py:416) → `_cancel_listeners` (hvac.py:2145) | None (timer fires once, unsub is idempotent) | ✅ |
| Post-release `async_create_task` re-kick (NEW) | `_pending_tasks` → `async_teardown` cancel loop (hvac.py:2137-2139) | **HIGH-B1: race with teardown on reload** | ⚠️ |

---

## No-fabrication discipline disclosures

Per the No-Fabrication rule, the following assertions in this review are inferred from HA dev-docs memory or from URA patterns in this repo, NOT verified against HA core source this session:

1. **`bus.async_listen_once` auto-removes the listener after firing AND its unsub callable is a safe no-op when called post-fire.** Source: HA dev docs + my prior URA usage notes; not re-verified in `homeassistant/core.py:EventBus.async_listen_once` this session. If this is wrong, MED-B2 may upgrade or change shape.
2. **`async_call_later` returns an unsub callable for an `async_track_point_in_utc_time` whose internal handle is cleared post-fire, making post-fire unsub a no-op.** Source: HA dev docs; not re-verified in `homeassistant/helpers/event.py` this session.
3. **HA `STARTING` state has `is_running == False` and HA transitions to `RUNNING` before firing `EVENT_HOMEASSISTANT_STARTED`.** Source: prior URA cycle notes; not re-verified in HA core state machine this session. If HA actually flips `is_running == True` BEFORE firing the event, MED-B3 is moot.
4. **HIGH-B1's parent-entry-reload race is plausible per the documented `parent reload watchdog` incident in `MEMORY.md` 2026-06-03**, but the exact sequence (whether pending sync callbacks drain before `async_teardown` is awaited on a parent reload) was not source-traced in `__init__.py` / `coordinator_manager.py` this session. The fix I recommend (option 1: defer re-kick via `async_call_later(1s)` stored in `_unsub_listeners`) is robust regardless of the exact sequence and is the safe option.

A builder fix-up pass or a follow-up review should confirm assertions 1-3 against HA core before treating MED-B2/B3 as anything other than "small-blast-radius hardening."
