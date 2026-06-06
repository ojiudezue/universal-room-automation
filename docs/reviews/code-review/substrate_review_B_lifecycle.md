# Occupancy Substrate Unification — Review B (Lifecycle / Smoothing / Listener-Rewire)

**Reviewer axis:** "right sensors, wrong timing/teardown" — temporal smoothing,
async/lifecycle, listener teardown, room-tier rewire actuation-critical path.
**Branch:** `feature/occupancy-substrate-unification`
**Diff scope:** `git diff develop..HEAD` (commit `e165e1c`)
**Date:** 2026-06-05
**Verdict:** **BLOCK** — one CRITICAL room-tier subscription-clobber must be
fixed before deploy. Two HIGH (latent #34, log-line ambiguity). Several MEDIUM
hardenings. Smoothing semantics PRESERVED. Zone-tier lifecycle CORRECT.

---

## Summary table

| Severity | ID | File | Topic |
|---|---|---|---|
| CRITICAL | B-C1 | `coordinator.py:986, 1039, 1053, 1066-1068` | Room-tier `SIGNAL_SUBSTRATE_KIND_CHANGED` subscription is CLOBBERED by `_update_signal_subscriptions()` immediately after it is registered. No room ever receives a substrate edge. |
| HIGH | B-H1 | `presence.py:1918, 1956` | Function-local `async_dispatcher_connect` imports — Bug Class #34 latent. |
| HIGH | B-H2 | `coordinator.py:1019-1026` | Log-line claims "X Tier 1 sensors via substrate signal" but the count INCLUDES lux (which is NOT in the substrate). Off-by-one operator-visible. |
| MEDIUM | B-M1 | `coordinator.py:894` | `tier1_sensors` still includes lux in the "Tier 1 sensors: %d %s" debug log — cosmetic, but operator may infer lux is in the substrate. |
| MEDIUM | B-M2 | `presence.py:1929` + `1246-1249` | `self._substrate_signal_unsub` field is set but never independently used; the unsub also lives in `_unsub_listeners`. Stylistic redundancy with footgun potential on re-setup. |
| MEDIUM | B-M3 | `occupancy_substrate.py:285` | `async_teardown` clears `_local_subscribers` — but re-discovery (`async_setup` called twice) does NOT. Asymmetric. Not a defect today (no subscribers), but reload semantics deserve a comment. |
| MEDIUM | B-M4 | `binary_sensor.py:556, 572` | Comment "function-local — Bug Class #34" cites the wrong bug class. `TIER1_KINDS` is a constant; #34 is about dispatcher imports. Misleading. |
| LOW | B-L1 | `occupancy_substrate.py:163-169` | Exception handler around `async_entries` is sound, but no `exc_info=True` on the `_LOGGER.warning` would lose the traceback — current code DOES pass it. (Noted as a positive.) |
| LOW | B-L2 | `coordinator.py:1027-1030` | `_ = occupancy_sensor_set` suppression with comment "kept for diagnostic parity" — dead code, prefer deletion or active use. |

---

## CRITICAL — B-C1: Room-tier substrate subscription is clobbered

### File:line
- `coordinator.py:986-992` — substrate subscription appended to `self._unsub_signal_listeners`
- `coordinator.py:1039` — `self._update_signal_subscriptions()` called immediately after
- `coordinator.py:1053` — `_update_signal_subscriptions()` ALSO called on every options-flow save
- `coordinator.py:1066-1068` — `_update_signal_subscriptions` clears `_unsub_signal_listeners` wholesale

### Evidence

`coordinator.py:986`:
```python
self._unsub_signal_listeners.append(
    async_dispatcher_connect(
        self.hass,
        SIGNAL_SUBSTRATE_KIND_CHANGED,
        _on_substrate_kind_changed,
    )
)
```

then immediately (`coordinator.py:1039`):
```python
# v3.12.0 M2: Subscribe to coordinator signals for trigger/AI-rule detection.
self._update_signal_subscriptions()
```

and inside `_update_signal_subscriptions` (`coordinator.py:1066-1068`):
```python
# Clear existing signal subscriptions
for unsub in self._unsub_signal_listeners:
    unsub()
self._unsub_signal_listeners.clear()
```

`_update_signal_subscriptions` rebuilds ONLY the M2 chain/AI-rule signal set
(`SIGNAL_HOUSE_STATE_CHANGED`, `SIGNAL_ENERGY_CONSTRAINT`,
`SIGNAL_SAFETY_HAZARD`, `SIGNAL_SECURITY_EVENT`). The substrate signal is NOT
in its `_signal_map` — so after line 1039, the substrate subscription is
**unsubscribed and never re-added**. Every Tier-1 edge dispatched by
`OccupancySubstrate._dispatch` for every room is silently dropped by the room
tier.

Same clobber repeats on every options-flow save (`coordinator.py:1052-1057`
wires `_update_signal_subscriptions` into `entry.add_update_listener`).

### Impact

- The D3 room-tier rewire (the planning doc's stated **actuation-critical**
  surface) has **zero reach**. Every motion / mmwave / occupancy edge that
  used to trigger `_tier1_state_changed → async_refresh()` is dropped.
- Room-tier reaction latency regresses from "immediate (≤2s rate-limited)" to
  "next 30s poll tick" — i.e. a ~15x worst-case latency regression on the
  actuation-critical occupancy path.
- The lux state-change listener at `coordinator.py:1013-1017` is on
  `_unsub_state_listeners` (not `_unsub_signal_listeners`) and survives —
  so lux edges still trigger refreshes. This masks the bug in superficial
  smoke tests: refreshes do happen, just driven by lux and the 30s poll, not
  by occupancy sensors.
- The zone tier is UNAFFECTED — its substrate subscription lives on
  `PresenceCoordinator._unsub_listeners`, which `_update_signal_subscriptions`
  does not touch. So zone-tier `_room_provenance` writes still flow.
  Room-tier smoothing in `_async_update_data` reads `hass.states.get()`
  directly, so when the 30s poll finally fires the data IS correct — but the
  reaction window is broken.

### Suggested fix

The cleanest fix is to move the substrate subscription off
`_unsub_signal_listeners` (which is owned by the M2 trigger machinery) and
onto `_unsub_state_listeners` (which is only cleared on
`async_config_entry_first_refresh` and on explicit teardown):

```python
# coordinator.py:986 — change list
self._unsub_state_listeners.append(
    async_dispatcher_connect(
        self.hass,
        SIGNAL_SUBSTRATE_KIND_CHANGED,
        _on_substrate_kind_changed,
    )
)
```

The name `_unsub_state_listeners` is slightly misleading once it holds a
dispatcher unsub, but the semantics match: both are "set up in first-refresh
event-listener block, torn down on reload/unload, never touched by the M2
options-update path."

Alternatively, add a dedicated `self._unsub_substrate_listeners: list` field
and clean it up in both `async_config_entry_first_refresh` (prior-state
sweep at line 865-870) and `async_teardown`. This is the more surgical
option and avoids overloading `_unsub_state_listeners` semantics.

Either fix must be accompanied by a new behavioral test:

```python
def test_substrate_subscription_survives_options_update():
    # First-refresh registers substrate sub
    # _update_signal_subscriptions runs (options update)
    # Substrate dispatch -> room coordinator MUST refresh
```

Without this test, any future re-shuffle of `_update_signal_subscriptions`
could re-introduce the clobber.

### Bug class

- **Bug Class #38** (listener cleanup gone wrong) — variant: cleanup path
  consumes a legitimate live subscription that should NOT have been pooled
  with the conditionally-rebuilt set.

### Verdict
**Must fix before deploy.** This is THE highest-impact lifecycle defect in the
cycle. The plan doc itself flagged D3 as the actuation-critical change; the
implementation broke it.

---

## HIGH — B-H1: Function-local `async_dispatcher_connect` imports (Bug Class #34 latent)

### File:line
- `presence.py:1918-1920` (substrate signal subscribe):
  ```python
  from homeassistant.helpers.dispatcher import (  # noqa: PLC0415
      async_dispatcher_connect,
  )
  ```
- `presence.py:1956` (census update subscribe):
  ```python
  from homeassistant.helpers.dispatcher import async_dispatcher_connect
  ```

Both live inside the SAME `async def async_setup` function.
`async_dispatcher_send` IS imported at module top (`presence.py:70`); only
`async_dispatcher_connect` is function-local.

### Why it matters

This is the **exact failure pattern** that produced the v4.7.20.1 hotfix
(Bug Class #34): a `from X import Y` inside a function body causes Python to
treat `Y` as a function-local name. If any code path in `async_setup`
references `async_dispatcher_connect` BEFORE the line-1918 import executes,
Python raises `UnboundLocalError` at the reference site, not at the import.

Today no path references it earlier in `async_setup`, so the cycle does not
ship a live regression — but the function is ~150 lines long and the next
edit that adds a conditional `async_dispatcher_connect` reference above
line 1918 will trip the UnboundLocalError.

### Suggested fix

Add `async_dispatcher_connect` to the module-top import alongside
`async_dispatcher_send`:

```python
# presence.py:70 — replace
from homeassistant.helpers.dispatcher import (
    async_dispatcher_send,
    async_dispatcher_connect,
)
```

Then delete both function-local imports (lines 1918-1920 and 1956). Also
sweep `presence.py:3220` (third function-local site, pre-existing).

### Bug class
**Bug Class #34** (function-local dispatcher import shadow-binding).

### Verdict
**Fix in this cycle.** Cheap (4-line change), eliminates a latent footgun
of the exact same shape the v4.7.20.1 hotfix existed to kill. Sibling
hardening to the substrate's own correct pattern (`occupancy_substrate.py:49`
keeps the import at module top — the substrate avoided the trap; the
PresenceCoordinator setup did not).

---

## HIGH — B-H2: Log-line over-counts Tier-1 sensors

### File:line
- `coordinator.py:894` — lux is added to `tier1_sensors`
- `coordinator.py:1019-1026`:
  ```python
  _LOGGER.info(
      "Room %s: Event-driven mode — %d Tier 1 sensors via "
      "substrate signal (%d motion / %d mmwave / %d occupancy), "
      "%d Tier 2 sensors (30s poll)",
      room_name, len(tier1_sensors),
      len(motion_sensors), len(mmwave_sensors),
      len(occupancy_sensors), tier2_count,
  )
  ```

`len(tier1_sensors)` includes lux, but the parenthetical breakdown
`(N motion / N mmwave / N occupancy)` does NOT. For any room with a lux
sensor configured, the totals don't add up:
`tier1_sensors = motion + mmwave + occupancy + lux`, but the log claims
`X = motion + mmwave + occupancy` "via substrate signal." Lux is
explicitly NOT via the substrate signal.

### Impact

- Operator-visible log noise during deploy validation. Sets the wrong
  expectation about substrate scope.
- More importantly: any post-deploy log audit checking "did substrate fan
  out to the right number of entities?" will compare the substrate's
  "subscribed to N Tier-1 entities" line (`occupancy_substrate.py:260-263`)
  against the room-tier "X Tier 1 sensors via substrate signal" line and
  see them disagree by one per lux-configured room (≈30 rooms × 1 lux
  each → 30 off-by-ones).

### Suggested fix

Either:
1. Exclude lux from `tier1_sensors` and treat lux separately throughout
   (cleaner, matches the substrate's view), OR
2. Change the log line to reflect actual scope:

```python
_LOGGER.info(
    "Room %s: Event-driven mode — %d substrate-driven Tier-1 sensors "
    "(%d motion / %d mmwave / %d occupancy)%s, %d Tier 2 sensors (30s poll)",
    room_name,
    len(motion_sensors) + len(mmwave_sensors) + len(occupancy_sensors),
    len(motion_sensors), len(mmwave_sensors), len(occupancy_sensors),
    " + 1 lux (direct)" if lux_entity else "",
    tier2_count,
)
```

### Bug class
Not bug-class-mapping; operator-visibility / observability hygiene.

### Verdict
**Fix in this cycle.** ~5 LoC. Resolves an audit-trail confound that will
otherwise burn validator time post-deploy.

---

## MEDIUM — B-M1: `tier1_sensors` debug log misleads

### File:line
- `coordinator.py:894` (lux appended) → `coordinator.py:906-908`:
  ```python
  _LOGGER.debug(
      "Room %s: Tier 1 (immediate) sensors: %d %s, Tier 2 (poll-only): %d",
      room_name, len(tier1_sensors), tier1_sensors, tier2_count,
  )
  ```

Same root cause as B-H2 but on the DEBUG log. `tier1_sensors` is the legacy
union; "Tier 1 (immediate)" is now ambiguous (immediate via substrate vs.
immediate via direct state-change). Lower severity because DEBUG.

### Suggested fix

Sibling to B-H2 — same restructure.

---

## MEDIUM — B-M2: `self._substrate_signal_unsub` field is redundant

### File:line
- `presence.py:1247-1249` — field declared
- `presence.py:1924-1929` — field set AND ALSO appended to `_unsub_listeners`

### Why it matters

The field is never read independently. `_cancel_listeners` (`base.py:282`)
walks `_unsub_listeners`, calling each unsub once. So teardown works
correctly today. But the field invites a future hotfix to assume it's the
canonical handle and call `self._substrate_signal_unsub()` directly — at
which point the unsub fires twice (raise once, then no-op or AttributeError
depending on HA's dispatcher impl).

### Suggested fix

Either:
1. Delete the `self._substrate_signal_unsub` field; rely on
   `_unsub_listeners` (Bug Class #38 doctrine: one storage path).
2. Keep the field but remove the `_unsub_listeners.append` — and add the
   field-direct unsub to `async_teardown`.

Option (1) is simpler and matches the pattern at `presence.py:1957-1963`
(census subscribe — only goes into `_unsub_listeners`, no field).

### Bug class
**Bug Class #38** (listener storage hygiene).

---

## MEDIUM — B-M3: Re-discovery doesn't clear `_local_subscribers`

### File:line
- `occupancy_substrate.py:282-285`:
  ```python
  async def async_teardown(self) -> None:
      """Unsub every listener and clear local subscribers."""
      self._teardown_listeners()
      self._local_subscribers.clear()
  ```
- `occupancy_substrate.py:143-153` — `async_setup` re-discovery only clears
  listeners (via `_teardown_listeners`), not local subscribers.

### Why it matters

Asymmetric semantics: `async_teardown` clears subscribers but `async_setup`
(when called for re-discovery) preserves them. This is **probably correct
intent** — re-discovery should preserve same-coordinator wiring like the
zone tier's subscribe — but the dispatcher signal path (line 1924-1929)
uses `async_dispatcher_connect`, not `substrate.subscribe()`. So there are
currently no users of `subscribe()` in the codebase.

If a future caller registers a `subscribe()` callback, then a room CONF
options-save triggers `async_setup` re-discovery, the subscriber is
preserved (good). If the user UNLOADS the integration without explicit
teardown, the `_local_subscribers` list dies with the substrate — no leak.
So the asymmetry is benign today.

### Suggested fix

Add a docstring note to `async_setup` explicitly stating "preserves
`_local_subscribers` across re-discovery (intentional)" so a future reader
doesn't 'fix' it.

### Bug class
None — documentation hygiene.

---

## MEDIUM — B-M4: Misleading "Bug Class #34" comment in binary_sensor.py

### File:line
- `binary_sensor.py:556`:
  ```python
  from .const import TIER1_KINDS  # function-local — Bug Class #34
  ```
- `binary_sensor.py:572`:
  ```python
  from .const import TIER1_KINDS  # function-local
  ```
- `binary_sensor.py:410` (pre-existing) has the same wording.

### Why it matters

Bug Class #34 is about function-local imports of `async_dispatcher_send` /
`async_dispatcher_connect` that shadow-bind names and cause `UnboundLocalError`.
`TIER1_KINDS` is a plain constant — function-local imports of constants
are stylistically odd but pose no Bug Class #34 risk. The comment misleads
future readers about what protective measure is being applied.

### Suggested fix

Either:
1. Move `TIER1_KINDS` to module-top import in `binary_sensor.py` (already
   imports `from .const`, just add the symbol). Delete all three
   function-local imports. Cleaner. — OR —
2. Change the comment to drop the "Bug Class #34" claim. The function-local
   pattern here was clearly inherited from the dispatcher-import doctrine
   but doesn't apply.

### Bug class
None — comment / documentation hygiene.

---

## Confirmed-correct surfaces (positive findings)

### S1. Substrate listener teardown is clean (Bug Class #38)
- `occupancy_substrate.py:287-297` — `_teardown_listeners` walks the unsub
  list defensively, swallows exceptions, clears the list.
- `async_setup` (line 153) calls `_teardown_listeners()` BEFORE re-discovery
  → stale listeners cannot accumulate on options-save / re-setup.

### S2. Substrate seed mirrors v4.7.18.1 B-HIGH-1 pattern
- `occupancy_substrate.py:236-246` — reads `hass.states.get(entity_id)` per
  discovered entity, agrees with reality on first post-settle tick.
- Zone-tier seed (`presence.py:2397-2414`) re-routes substrate's view into
  the tracker's `_room_provenance` so Invariant 4
  (`set(_room_provenance.keys()) == set(_room_occupied.keys())`) holds even
  for rooms with no currently-True kind.

### S3. Boot-settle gate cascade is correct
- `presence.py:1700-1714` — `_release_boot_settle` is idempotent (line
  1698 guard) and unconditionally cascades to
  `self._substrate.release_boot_settle()`.
- Reload path (`presence.py:1908-1915`) explicitly releases substrate gate
  when `_boot_settle_done` is already True at substrate setup time.
- Substrate gate flip emits ONE synthetic dispatch per True (room, kind)
  slot (`occupancy_substrate.py:315-321`) — False slots silent → no
  per-room storm.

### S4. Smoothing pipeline UNCHANGED
- Room tier's `_async_update_data` (`coordinator.py:1301-`) reads
  `hass.states.get()` for every motion/mmwave/occupancy sensor directly —
  substrate only TRIGGERS the refresh; it does NOT feed the smoothing
  state. So the ~900s timeout, failsafe duration, camera override, and
  BLE override pipeline are all bypassing the substrate and continue
  byte-equivalent to develop. **This is the cycle's most important
  correctness invariant and it is preserved.**

### S5. v4.7.18.1 wake-timer dependency on `raw_occupied` preserved
- `presence.py:575-582`:
  ```python
  @property
  def raw_occupied(self) -> bool:
      return self._derived_mode == ZonePresenceMode.OCCUPIED
  ```
- `_derived_mode` reads `self._room_occupied` which is now a computed
  property (`presence.py:487-505`) returning
  `{room: any(_room_provenance[room].values())}` — equivalent to the
  pre-cycle bool view.
- Substrate edges flow into `_room_provenance` via
  `tracker.update_room_occupancy(room, new_state, kind=kind)` at
  `presence.py:2448`. Same call shape as the prior live-path call.
- Net: `raw_occupied` semantics survive byte-for-byte. v4.7.18.1 wake
  timer keeps working.

### S6. Substrate's own dispatcher import is at module top
- `occupancy_substrate.py:49`:
  `from homeassistant.helpers.dispatcher import async_dispatcher_send`
  → no Bug Class #34 hazard inside the substrate itself.

### S7. Lux subscription correctly survives
- `coordinator.py:1013-1017` — lux state-change subscription is appended
  to `_unsub_state_listeners` (NOT `_unsub_signal_listeners`), so it
  survives `_update_signal_subscriptions` clobber.
- Shares the same `_trigger_rate_limited_refresh()` closure as the
  substrate handler → no double-refresh, no dropped lux updates.
- (The fact that lux still works while the substrate sub is clobbered is
  exactly what would mask B-C1 in a casual smoke test.)

### S8. Coordinator default debouncer unchanged
- `coordinator.py:286-291` — `super().__init__` passes
  `update_interval=timedelta(seconds=30 + jitter)` and NO `request_refresh_debouncer`
  kwarg. So HA's default (cooldown=10s, immediate=True) applies. The
  cycle's decision to keep `async_refresh()` (immediate, bypasses the
  10s default debouncer) at line 920-924 is correct and preserves the
  B-HIGH-1 / v4.7.18.1 fix. — If B-C1 is fixed (so the substrate handler
  actually fires), Tier-1 latency stays at parity.

### S9. Substrate teardown is wired into `async_teardown`
- `presence.py:5315-5323` — `_substrate.async_teardown()` is called
  BEFORE `_cancel_listeners`, so the substrate's per-entity state-change
  listeners are released before the dispatcher signal subscription is
  torn down (correct order — no race on a final edge).

---

## Risk-axis coverage scorecard

| Reviewer-B risk | Status |
|---|---|
| 1. D3 room-tier listener rewire byte-for-byte preservation | **BROKEN** (B-C1) — leading-edge immediate `async_refresh()` semantics correct on paper, but the handler is never reached because the subscription is clobbered |
| 2. Lux survival + no double-refresh / dropped updates | **OK** (S7) |
| 3. Room-tier smoothing pipeline (timeout/failsafe/camera/BLE) byte-equivalent + v4.7.18.1 wake timer | **OK** (S4, S5) |
| 4. Bug Class #38 (listener teardown) audit across substrate + presence + coordinator | **OK except B-C1's cleanup pooling defect**; substrate teardown is clean (S1); presence teardown clean (S9); coordinator teardown corrupted by `_update_signal_subscriptions` overload (B-C1) |
| 5. Bug Class #34 (function-local dispatcher import) | **LATENT** (B-H1) — substrate is clean (S6), but presence.py has two function-local `async_dispatcher_connect` imports inside `async_setup` |
| 6. D6 boot-settle gate read + no pre-settle edge loss | **OK** (S3) — gate cascade idempotent, replay covers True slots, False slots default-False in consumers |
| 7. Seed-on-startup mirrors v4.7.18.1 B-HIGH-1 | **OK** (S2) |

---

## Final verdict

**BLOCK.**

Fix B-C1 (CRITICAL room-tier subscription clobber) and B-H1 (HIGH latent
Bug Class #34) before deploy. B-H2 (off-by-one operator log) is worth
fixing in the same fix-up pass — small surface, prevents post-deploy
validator confusion.

The MEDIUMs are operator-visible hygiene and can be fixed in this cycle
per the "Fix LOWs/MEDIUMs in-cycle" feedback memo (2026-06-02), but are
not deploy-blocking on their own.

**B-C1 specifically is the kind of defect the Tier-2 review protocol
exists to catch.** A single review framing on "correctness" might have
classified `async_dispatcher_connect` registration as obviously correct
without auditing the very next line of execution. The lifecycle framing
caught it by walking forward from the registration site to find
`_update_signal_subscriptions()` clearing the same list 53 lines later.

After B-C1 fix, re-verify with a behavioral test that simulates an options-flow save
between substrate setup and a substrate dispatch — the test must assert
the room coordinator's refresh is triggered.

---

## Out of scope (Reviewer A / Reviewer C lanes)

These were noted while reviewing but defer to the other reviewer framings:
- Discovery correctness for multi-list CONF membership (precedence order
  motion → mmwave → occupancy) — Reviewer A surface.
- Test fixture authority + behavioral coverage of substrate against real
  schemas — Reviewer C surface.
- Substrate's CONF surface vs. legacy area-sweep ripple consumers (audit
  doc `AUDIT_occupancy_substrate_consumer_ripple.md`) — Reviewer C surface.

---

## Fix-up resolution (2026-06-05, commit 1de2ae1)

- **B-C1 CRITICAL — FIXED.** Dedicated `_unsub_substrate_listeners` list
  (`coordinator.py:272`), appended at `:1008`, torn down at `:883-885`
  (reload-clear) and `__init__.py:3170` (unload). `_update_signal_subscriptions()`
  no longer touches it. New behavioral regression guard
  `test_room_substrate_integration.py::test_room_handler_survives_signal_listener_clobber`
  simulates the options-save clobber and asserts the edge survives.
  Filed as QUALITY_CONTEXT Bug Class #50.
- **B-H1 HIGH — FIXED.** Function-local `async_dispatcher_connect` imports
  at `presence.py:~1918,~1956` hoisted to module-top; third local alias
  replaced. (Bug Class #34.)
- **B-H2 HIGH — FIXED.** Log line now reports substrate-routed count
  (motion+mmwave+occupancy) and lux separately (`coordinator.py:1027-1051`).
- MEDIUMs: B-M4 comment misattribution fixed; B-M1/2/3 deferred (non-load-bearing).
- Verified: 45 cycle tests pass; full suite 5034 passed / 62 pre-existing
  failures (no new regressions); compile clean; no conflict markers.
