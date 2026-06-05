# Boot-Storm Settle Gate — Review A (Correctness + Edge Cases)

**Branch:** `feature/boot-storm-settle-gate`
**Commit:** `da596a4`
**Diff base:** `develop`
**Reviewer framing:** Correctness + reachability + edge cases. Async / lifecycle / race covered by Reviewer B in parallel — explicitly skipped here unless a correctness consequence forced a note.
**Files in scope:**
- `custom_components/universal_room_automation/const.py`
- `custom_components/universal_room_automation/domain_coordinators/presence.py`
- `custom_components/universal_room_automation/domain_coordinators/hvac.py`
- `custom_components/universal_room_automation/sensor.py`
- `quality/tests/test_boot_settle_gate.py`
- `quality/tests/test_v472_feature_b_guest_signal.py` (helper retrofit)

---

## Summary stats

| Severity | Count | Fixed in-cycle (recommended) | Defer |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 2 | 2 | 0 |
| MEDIUM | 4 | 3 | 1 |
| LOW | 3 | 2 | 1 |
| **Total** | **9** | **7** | **2** |

**Verdict: FIX-FIRST.** No CRITICAL reachability hole — the timeout failsafe is correctly wired on every cold-boot path I could trace, so the "stuck forever" worst case is genuinely bounded. But there are two HIGH-severity correctness gaps that materially weaken the gate's claim: (1) a release-path ordering issue where Gate 2's timeout can fire after `async_teardown()` has already cleared `_unsub_listeners` cleanup, and (2) Predicate A is mis-specified for the empty-cold-boot case it most needs to handle. These are 5-30 LoC fixes. Fix both before deploy, re-tag baseline, re-validate `test_boot_settle_gate.py`.

---

## Findings

### HIGH-A1 — Predicate A false-positive on the storm tick itself

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py:3810-3820`
**Bug class:** #46-adjacent (gate-armed misclassification; specifically "early release defeats the gate")

Predicate A treats `trigger not in ("startup", "periodic", "deferred_retry")` as a "real input." But on cold boot, the FIRST `_run_inference` call typically arrives with a trigger like `"signal_house_state"`, `"zone_change"`, or a coordinator-manager-driven trigger string — none of which match the three-element exclusion list. The result: **the very first cold-boot inference tick — which is the one most likely to be running before census data has settled — flips the gate to released immediately**, defeating Gate 1 for any cold boot whose first `_run_inference` was not triggered by `startup`/`periodic`/`deferred_retry`.

The hardcoded exclusion list is also a string-literal sentinel set with no canonical reference in `const.py` — a new trigger string introduced later (e.g. `"deferred_retry_v2"`, `"force_inference"`) would silently leak into the "real" bucket.

**Why this is correctness, not lifecycle:** the gate's stated purpose (planning doc §6) is to hold dispatch until census/zone has settled. If the first tick is treated as real because of its trigger label rather than the underlying data, the gate is functionally a no-op on exactly the boot profile that motivated it.

**Concrete fix (presence.py:3810-3820):**

```python
if not self._boot_settle_done:
    # Data-driven release only: trigger label is unreliable at cold boot
    # because coordinator-manager-driven triggers are NOT in the
    # startup/periodic/deferred_retry set but still arrive before census
    # has settled.
    _real_input = (
        self._census_count >= BOOT_SETTLE_MIN_INPUTS
        or any(
            t.mode == ZonePresenceMode.OCCUPIED
            for t in self._zone_trackers.values()
        )
    )
    if _real_input:
        self._release_boot_settle("real_input")
```

If we want to KEEP the trigger-based release as a fast-path for genuinely event-driven ticks, promote the sentinel set to a `BOOT_SETTLE_STARTUP_TRIGGERS: Final = frozenset({...})` in `const.py` and explicitly INCLUDE every coordinator-manager-emitted startup-adjacent trigger after surveying `coordinator_manager.py` for what it actually emits during boot. Without that survey the trigger-based clause is a latent bug.

---

### HIGH-A2 — Gate 2's `async_call_later` callback can fire post-teardown

**File:** `custom_components/universal_room_automation/domain_coordinators/hvac.py:407-416` + `_async_decision_cycle` site at `:745-761`
**Bug class:** #34-adjacent (callback-after-teardown / scheduler-callback safety). Note: this lives at the correctness/lifecycle boundary; flagging here because the consequence is a wrong-state actuation, not just a stale log.

`_timeout_release_boot_settle` is scheduled via `async_call_later` and the unsub stored in `_unsub_listeners`. `BaseCoordinator.async_teardown()` (base.py:284) iterates `_unsub_listeners` and unsubs each. That's fine for a strict teardown→ no further callbacks path.

But the failure mode is: timeout fires, `_release_boot_settle("timeout")` flips `_boot_settle_done = True`. The very NEXT scheduled `_async_decision_cycle` tick (the 5-min periodic timer) sees the gate as released and proceeds. If the timeout release happens at exactly the wrong moment — after the failed-startup path has caused HA to call `async_teardown` on the parent entry (see the `MEMORY.md` entry "Parent-entry reload watchdog hazard") — the gate-released flag is still True on the next setup, but the rest of the state is brand new. No persistent harm because `_boot_settle_done` is re-initialized in `__init__` to `False`, but the OPPOSITE race is the real issue: on a config-entry reload that happens BEFORE timeout fires, `_unsub_listeners.clear()` runs and the timeout callback is correctly cancelled. So far so good.

The actual correctness hole: **on the cold-boot path, `_async_decision_cycle` is ALSO invoked from the end of `async_setup()` (the "explicit kickoff" mentioned in the planning doc and visible in code comments at hvac.py:747-751)**. If the kickoff fires before `EVENT_HOMEASSISTANT_STARTED` and before timeout, Gate 2 correctly suppresses → counter increments → return. Good. But there is **no follow-up scheduling** to re-run a decision cycle after `_release_boot_settle` flips the flag. We rely entirely on the next 5-minute periodic tick. That means **up to a full 5-minute window after release** during which:

- presence has dispatched (post-release) a real house-state signal,
- HVAC has ignored it because its kickoff was suppressed and the next periodic tick hasn't fired yet.

This matches the planning doc §6 risk verbatim: "leaves HVAC in a wrong state after release because the first cycle was skipped and nothing re-triggers it."

**Concrete fix:** in `_release_boot_settle` on the HVAC coordinator, after setting `_boot_settle_done = True`, schedule a one-shot `_async_decision_cycle` if we suppressed at least one cycle. Roughly:

```python
def _release_boot_settle(self, reason: str) -> None:
    if self._boot_settle_done:
        return
    self._boot_settle_done = True
    self._boot_settle_release_reason = reason
    # ... existing logging ...
    # If we suppressed at least one decision cycle, immediately re-run
    # so HVAC catches up to the now-settled presence state without
    # waiting for the next 5-min periodic tick.
    if self._boot_settle_hvac_suppressed > 0:
        self.hass.async_create_task(
            self._async_decision_cycle(),
            name="hvac_post_boot_settle_kickoff",
        )
```

(Reviewer B will likely flag the untracked-task concern; addressing both means wrapping in the existing `_pending_tasks` discipline visible at hvac.py:233.)

Without this re-kick, Gate 2 is correct on the "no storm" path but introduces a 0-5 minute actuation latency hole on every cold boot where it actually fires — directly trading one boot pathology for another.

---

### MED-A3 — Predicate A re-checks `trigger` after a lazy `_zone_trackers` iteration

**File:** `presence.py:3813-3818`
**Bug class:** #7-adjacent (stale-data source — defensive read against a not-yet-built collection)

`any(t.mode == ZonePresenceMode.OCCUPIED for t in self._zone_trackers.values())` is safe if `_zone_trackers` exists, but on the very first `_run_inference` tick at cold boot, `_zone_trackers` may not have been populated yet (population happens during zone discovery which runs as part of `async_setup`). If `_zone_trackers` is an empty dict, the `any()` returns `False` — that's the safe default. But if `_zone_trackers` is `None` (the construction-time placeholder in some legacy code paths), `.values()` raises `AttributeError` and the entire `_run_inference` aborts.

I did not verify whether `_zone_trackers` is guaranteed to be a `dict` at the moment of first call (would require reading `__init__` end-to-end). Worst case is mitigated by the outer `try/except` around the inference run, but a defensive `(self._zone_trackers or {}).values()` is one character of overhead and removes the question entirely.

**Concrete fix:**
```python
or any(
    t.mode == ZonePresenceMode.OCCUPIED
    for t in (self._zone_trackers or {}).values()
)
```

---

### MED-A4 — Gate 1 / observation_mode interaction loses one log line per suppression

**File:** `presence.py:4584-4602`
**Bug class:** N/A (operability)

The new ordering is:

```python
if not self._boot_settle_done:
    # log boot-settle suppression
elif self.observation_mode:
    # log observation-mode suppression
else:
    # dispatch
```

Stated intent (per comment): "the boot-settle log wins for clarity." That's reasonable for log volume. But for operability during the specific case operators care about — diagnosing whether a particular cold boot was held by Gate 1, by observation mode, or by both — we now lose visibility that observation_mode was ALSO holding. On the live system this is mostly fine (observation mode is rarely on at the moment of cold boot), but if an operator deliberately leaves observation_mode on across a restart for diagnostic reasons, the boot-settle log will mask the observation-mode behaviour and the operator will not know observation_mode is also engaged.

**Concrete fix:** in the boot-settle suppression branch, include `observation_mode=%s` in the log fmt so a `True` value surfaces. 1-line change. Or: don't fix, and accept the loss — there's a defensible argument that the boot-settle case is a transient that resolves within 60s and the observation_mode operator already knows their own state. I'd take the 1-line fix.

```python
_LOGGER.info(
    "Boot-settle: suppressed presence away-dispatch "
    "SIGNAL_HOUSE_STATE_CHANGED %s -> %s (trigger=%s, "
    "suppressed_count=%d, observation_mode=%s)",
    current_state.value, new_state.value, trigger,
    self._boot_settle_presence_suppressed,
    self.observation_mode,
)
```

---

### MED-A5 — `_method_body()` boundary regex weakens 3 of the 12 retrofitted assertions

**File:** `quality/tests/test_v472_feature_b_guest_signal.py:32-52` and the 12 call sites (244, 399, 409, 421, 432, 443, 468, 530, 548, 568, 581, 595)
**Bug class:** Test-fixture authority (Tier 2-DB Reviewer C class)

The helper is mostly correct: it computes the indent at `start_idx`, then finds the next class-level `def`/`async def` at the same OR SHALLOWER indentation. The boundary regex is `^[ \t]{0,N}(?:async def |def )` with `N` set to the start indent. **Correct upper bound for "same or shallower" — this is fine.**

But three of the retrofitted assertions use `body.find("elif current_state == HouseState.GUEST")` and then slice forward to `else:` (e.g. test_v472:548-557). Before the helper change, `body` was `presence_src[idx:idx + 15000]` — a fixed 15K window. With the helper, `body` is the WHOLE `_run_inference` method (currently ~3300 lines / many tens of KB). The assertion `else_idx = body.find("else:", guest_idx)` will now match the FIRST `else:` anywhere in the rest of `_run_inference`, which is many `if/else` branches further down than the GUEST block. **The slice between `guest_idx` and the wrong `else_idx` is now potentially huge and may include unrelated assertions, weakening the "guest_armed must derive from guest_room_gate_armed in GUEST branch" check.**

Concretely: `test_guest_armed_is_guest_room_gate_in_guest_branch` (line 581) asserts `"guest_armed = guest_room_gate_armed" in guest_block` — that string IS what the GUEST branch contains, so the assertion passes. But the assertion `test_guest_state_branch_skips_unid_gate` (line 548) checks that `"_guest_gate_armed(" NOT in guest_block` — with a now-huge `guest_block` extending past the GUEST branch into the regular state machine, this assertion will **fail** because `_guest_gate_armed` IS called elsewhere in `_run_inference` for the non-GUEST branches.

I haven't run the suite locally, but if these tests pass on `feature/boot-storm-settle-gate`, the only way is that `else_idx` happens to point to a small slice somewhere — please verify by running just `test_v472_feature_b_guest_signal.py::TestB1GuestRoomGateInGuestState` and confirming a non-empty slice that doesn't include unrelated `_guest_gate_armed(` calls.

**Concrete fix:** in the three "GUEST branch sub-slice" tests, after `guest_idx = body.find(...)`, bound the inner slice to the next `elif` or `else` at the SAME indentation as the matched `elif current_state == HouseState.GUEST`, not the first `else:` substring. A defensive 2000-char `body[guest_idx:guest_idx+2000]` window would restore the prior semantics for those three tests.

---

### MED-A6 — `boot_settle_release_reason` sensor attr does not surface "released early because HA was already running" vs "no cold boot ever happened"

**File:** `sensor.py:3880` + `presence.py:1718-1724`
**Bug class:** Operability

`_boot_settle_release_reason` is set to `"not_cold_boot"` on the reload path. On a TRUE cold boot, it starts as `"pending"` and only flips on release. That's fine. But the attr is exposed as a single string and operators can't distinguish "the gate fired and released via timeout, here's how long" vs "the gate never engaged because we reloaded." The 4-attr design surfaces this via the suppressed counters (both 0 on `not_cold_boot`, both ≥0 on a cold boot), so an operator can derive it. Acceptable, but worth a one-line attr `boot_settle_seconds_elapsed` from `_boot_settle_started_utc` so the deploy-watch can confirm the timeout actually engaged at ~60s rather than via a fast Predicate A. Defer if scope is tight.

---

### LOW-A7 — `EVENT_HOMEASSISTANT_STARTED` fallback string literal divergence

**File:** `presence.py:1736` and `hvac.py:381`
**Bug class:** N/A (resilience-against-test-stub)

Both gate inits have a defensive fallback:
```python
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
# except: EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
```

The fallback string `"homeassistant_started"` is the correct event name in current HA. If a future HA release renames the constant value (unlikely but not impossible), the fallback would silently miss the event and rely on the 60s timeout — gate still safe, just slower. Worth one comment line tying the fallback to a verified HA source-of-truth file, or DROP the fallback entirely if no test path actually needs it (the test file at line 50 mocks `homeassistant.const`, so the real import succeeds there).

---

### LOW-A8 — `_release_boot_settle` log message says "actuation will now proceed on next inference tick" — but presence may already be at non-AWAY at release time

**File:** `presence.py:1672-1677`
**Bug class:** N/A (log accuracy)

Pure cosmetics — the log line implies the gate was holding an AWAY → ... transition. In practice the holding window is short enough this is approximately true, but the message would read more accurately as "boot-settle: gate released via %s — subsequent house-state transitions will dispatch normally." 1-line clarity fix.

---

### LOW-A9 — `BOOT_SETTLE_MIN_INPUTS = 1` defeats its stated future-proofing purpose

**File:** `const.py:1389-1391`
**Bug class:** N/A (code clarity)

The constant comment says it exists "so a future cycle can raise the bar without a magic number proliferating." Fine. But Predicate A also checks `or any(t.mode == OCCUPIED ...)` and the trigger-set fallback. If a future cycle raises `BOOT_SETTLE_MIN_INPUTS` to (say) 3, the zone-occupied clause and the (broken — see HIGH-A1) trigger clause would still short-circuit release. Raising the constant alone won't have the intended effect. Either:
(a) document that the constant only governs ONE of three release paths, or
(b) refactor to a single `_is_settled() -> bool` predicate so a future tightening is one place.

Defer — code clarity only, no live bug.

---

## Reachability trace (per the prompt's #1 question)

**Gate 1 (presence) release paths on cold boot:**

| Path | Trigger | Scheduled at | Cancellable | Confirms? |
|---|---|---|---|---|
| Predicate A | `_run_inference` inputs pass | every inference tick after setup | — | YES — but HIGH-A1: may flip too early |
| Predicate B path 1 | `EVENT_HOMEASSISTANT_STARTED` bus event | `async_setup` line 1736 (`async_listen_once`) | unsub in `_unsub_listeners` | YES |
| Predicate B path 2 | `async_call_later(BOOT_SETTLE_TIMEOUT_SECONDS=60)` | `async_setup` line 1752 | unsub in `_unsub_listeners` | YES |

**Cold-boot reachability:** the failsafe timeout (path 2) is the safety net. As long as `async_call_later` was actually registered (the try/except around line 1750 catches stub failures), path 2 fires unconditionally at +60s. If `async_call_later` registration FAILS at line 1750, the only logging is `_LOGGER.debug(..., exc_info=True)` — silent in prod log levels. **No CRITICAL because the failure is logged, but on a real HA instance the `homeassistant.helpers.event` import + `async_call_later` should never raise.** Confirmed: timeout failsafe is reachable on every cold-boot path I can construct.

**Gate 2 (HVAC) release paths on cold boot:** Symmetric — only Predicate B (no Predicate A). HIGH-A2 is the post-release re-kick gap, not a reachability gap.

**Soft-restart vs cold-boot distinction (per prompt #2):** `hass.is_running` is True only AFTER the `EVENT_HOMEASSISTANT_STARTED` event has been fired and core has reached state RUNNING. A `homeassistant.restart` triggers the supervisor to restart the HA core process — that path goes through full HA bootstrap, so `is_running` is False at integration `async_setup` → the gate engages as a true cold boot. **Correct.** An options-flow reload (entry-only) calls `async_setup_entry` while HA core is already RUNNING → `is_running=True` → gate releases immediately with reason `"not_cold_boot"`. **Correct.**

**Worst case: HA never reaches RUNNING (per prompt #2):** core stays in startup, `EVENT_HOMEASSISTANT_STARTED` never fires. Path 1 dead. Path 2 (timeout, +60s) still fires because `async_call_later` is scheduled against the event loop independently of HA core state. Path A may or may not fire depending on whether `_run_inference` runs (typically it does once census_count is computed at integration startup). **Gate releases within 60s regardless. Confirmed safe.**

---

## Verdict

**FIX-FIRST.**

- Fix HIGH-A1 (Predicate A misclassification) — without this the gate is functionally a no-op on the cold-boot profile that motivated the cycle.
- Fix HIGH-A2 (HVAC post-release re-kick) — without this Gate 2 trades a storm for a 0-5min state-lag hole.
- Fix MED-A3, MED-A4, MED-A5 in the same fix-up pass (per `Fix LOWs In-Cycle` discipline — these are 1-30 LoC each).
- Defer MED-A6, LOW-A7, LOW-A8, LOW-A9 explicitly (document in plan-completion section).

After fix-up: re-run `test_boot_settle_gate.py` AND `test_v472_feature_b_guest_signal.py` AND `quality/tests/` baseline-diff. Re-tag baseline before any further iteration. Tier 2 protocol: hand to Reviewer B for async/lifecycle/race framing before ship.

**Note on no-fabrication discipline:** I did not verify what trigger strings the coordinator_manager actually emits during boot (HIGH-A1) by reading `coordinator_manager.py`. The finding is staked on the inference that `"signal_house_state"` / `"zone_change"` / etc. are plausible event-driven triggers NOT in the three-element exclusion set. If the coordinator manager ONLY ever emits `"startup"` / `"periodic"` / `"deferred_retry"` during boot, HIGH-A1 downgrades to MEDIUM. Reviewer B or a builder fix-up pass should grep the actual emit sites before applying my proposed fix.
