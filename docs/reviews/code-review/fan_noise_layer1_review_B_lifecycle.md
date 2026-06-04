# Fan-noise mitigation D1 — Reviewer B (Async + lifecycle + restart + cross-coordinator ripple)

**Branch:** `feature/fan-noise-layer1`
**Commit reviewed:** `9522d0f04c187556a0b8d931825de4342ed1d1d3`
**Base:** `develop` (`bf6b41a`)
**Framing:** B — async/lifecycle/restart/ripple. Findings target what A (correctness truth-table) and C (new-surface) are NOT looking at.
**Verdict:** **GREEN with HIGH issues.** AUDIT doc's ripple GREEN verdict largely holds — the truth-preserving invariant is correctly enforced in the property. But two lifecycle defects must be fixed before deploy: (B-H1) entry-options seed is wired ONLY through RestoreEntity (operator value silently reverts to 300s after a "Restored from Backup" or fresh install + restored config), and (B-H2) the dispatch site can crash the inference tick on a re-entrant import failure path. There is also one quiet ripple concern (B-H3 — `log_zone_event` over-attribution).

---

## Findings by severity

| Sev | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 3 |
| MEDIUM | 4 |
| LOW | 3 |

---

## CRITICAL — none

The truth-preserving invariant at `presence.py:_room_occupied` (the OR short-circuits FIRST) was independently re-verified by reading the property body + the 12 consumers in the AUDIT doc. No consumer can see a `False` for a room whose `_room_provenance` has any `True` kind. The ripple GREEN verdict is upheld.

The `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` dispatch was checked for Bug Class #42 (lambda + `async_create_task` in scheduler callbacks). The site at `presence.py:~4477` is a direct `async_dispatcher_send(...)` from within the awaited `_run_inference` coroutine — runs on the event-loop thread. No lambda, no thread-jump, no untracked task. SAFE.

---

## HIGH

### B-H1 — `CONF_FAN_INTERFERENCE_HOLD_S` operator value never reaches the coordinator after restart absent a working RestoreEntity round-trip
**Bug class:** #1 (seed-vs-live divergence) + #14 (first-tick post-restart rehydration)
**File:** `presence.py:1063-1066` + `number.py:FanInterferenceHoldNumber.__init__` + `number.py:async_added_to_hass`

`PresenceCoordinator.__init__` hard-codes `self._fan_interference_hold_s = DEFAULT_FAN_INTERFERENCE_HOLD_S` (300). It does NOT read `entry.options.get(CONF_FAN_INTERFERENCE_HOLD_S, DEFAULT)` from any config entry. The ONLY path that pushes a non-default value into the coordinator is `FanInterferenceHoldNumber.async_added_to_hass()` → `RestoreEntity.async_get_last_state()` → `_push_to_coordinator()`.

Failure modes:
1. **Fresh install with HACS restore of config (no recorder DB carry-over):** RestoreEntity has no last state → Number stays at default 300 → operator's previously-set 600s is lost silently.
2. **HA "Restored from Backup" path:** the recorder is rebuilt; RestoreEntity may not have the value at the FIRST post-restore restart.
3. **Number entity disabled or renamed by operator:** `async_added_to_hass` never fires → coordinator stays at 300 forever.
4. **The CONF_* constant exists in `const.py` but is read by NO code path** other than the Number's `__init__` default — defeats the documented "configurable via options flow" pretense (options_flow.py was not modified for this CONF; only `CONF_ADJACENT_ROOMS` was).

**Fix:** in `PresenceCoordinator.__init__`, after registering the entry, read the value from the CoordinatorManager entry's options:
```python
cm_entry_options = ...  # the coordinator_manager entry.options
self._fan_interference_hold_s = int(cm_entry_options.get(
    CONF_FAN_INTERFERENCE_HOLD_S, DEFAULT_FAN_INTERFERENCE_HOLD_S,
))
```
AND mirror the operator value back to `entry.options` when the Number pushes (the mirror pattern documented in `feedback_ura_mirror_pattern.md`). The Number-only RestoreEntity path is fragile.

### B-H2 — Dispatch site can raise on `from .signals import ...` and the `except` swallows but the `import` is repeated EVERY tick a new room is gated
**Bug class:** #34 (function-local import in hot path)
**File:** `presence.py:4476-4490`

```python
if newly_gated:
    try:
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        from .signals import SIGNAL_FAN_INTERFERENCE_GATE_FIRED
        async_dispatcher_send(...)
```

Two issues:
1. The `from .signals import ...` runs on EVERY tick that newly-gates a room. Python's import cache makes this O(1) after the first hit, but it's still a dict lookup + GIL acquire in the hot inference loop. Other dispatch sites in this same file (`SIGNAL_PRESENCE_ENTITIES_UPDATE` at `:4228`) use the same pattern, so this is consistent with prior art — call it a STYLE convention, not a fix-required.
2. The bigger concern: the `except Exception` swallows ALL errors silently at `_LOGGER.debug` level. If `signals.py` ever fails to import (circular import — possible during a refactor), the gate dispatch would silently stop firing and there would be NO INFO/WARNING signal in the logs. Demote `_LOGGER.debug` to `_LOGGER.warning` for the import-failure case, OR hoist the import to module top.

**Fix:** hoist the two imports to module top (they're already imported elsewhere in this same file at `:4227-4228`). Removes the per-tick cost and surfaces import failures at boot.

### B-H3 — `log_zone_event` over-attributes hold-extended rooms to the persisted DB row, making post-hoc forensics misleading
**Bug class:** #7 (stale data source / source-of-truth confusion)
**File:** `presence.py:4206-4216`

```python
occupied_rooms = [
    rn for rn, occ in tracker._room_occupied.items() if occ
]
self.hass.async_create_task(
    db.log_zone_event(
        zone=zone_name,
        event_type=new_mode,
        room_count=len(occupied_rooms),
        rooms=occupied_rooms if occupied_rooms else None,
    )
)
```

`tracker._room_occupied` is the derived view that INCLUDES hold-extended rooms. When a zone transitions OCCUPIED→AWAY (which can only happen because ALL rooms read False), this site is fine. But when the zone transitions OCCUPIED→OCCUPIED-via-extension or stays OCCUPIED because of hold, the `room_count` field in the DB log is INFLATED by hold-extended rooms.

The AUDIT doc marks this consumer SAFE because it preserves the "what the gate decided" semantic. I disagree — the DB log is the forensic surface operators consult to answer "why did Bedroom 2 stay occupied at 3am?" If the answer is "fan-interference hold," that should be DISTINGUISHABLE from "mmwave was actually firing."

**Fix:** add a sibling field `gated_rooms: list[str]` to the `log_zone_event` payload (or to a sidecar attribute on the row) so post-hoc queries can join against it. Defer to D2 if it touches the DB schema. For D1 — at minimum, when `_room_provenance` is empty for a room in the `occupied_rooms` list, prefix the room name with `"(hold) "` so the existing TEXT column shows the distinction. Or: emit a separate `log_fan_interference_event` row so the standard `log_zone_event` row stays clean.

---

## MEDIUM

### B-M1 — Adjacency map is rebuilt every tick by scanning ALL config entries
**Bug class:** Performance (no class yet; closest is the boot-cost concern from the v4.7.18.2 cycle)
**File:** `presence.py:2562-2610`

The block scans `self.hass.config_entries.async_entries(DOMAIN)` (could be 30+ entries for the operator's install) on EVERY `_apply_fan_interference_gate` call. The gate runs at every `_run_inference` tick — `periodic` + `occupancy_change` + `camera_detection` + `guest_*` — easily 10+ ticks/min during a busy evening.

Adjacency only changes on options-flow round-trip (rare). Cache it on the coordinator and invalidate on `SIGNAL_INTEGRATION_OPTIONS_UPDATED` (or whatever signal fires on options-flow save). This is a pre-emptive fix — current cost is microseconds, but the pattern repeated in future cycles becomes a problem.

**Fix:** memoize `adjacency` on `self._adjacency_cache: Optional[Dict[str, List[str]]] = None`. Invalidate on options-flow update signal.

### B-M2 — First-tick-post-restart can populate `_fan_interference_hold_until` from a half-built `_room_provenance` if a fan-on state arrives via event before `_run_inference("startup")` completes
**Bug class:** #14 (first-tick post-restart rehydration)
**File:** `presence.py:_apply_fan_interference_gate`

`_compute_fan_interference_rooms` requires `_fan_on_rooms` to be non-empty. On a cold boot, `_fan_on_rooms` is populated via `_discover_room_fans` which subscribes to fan entity state-change events. If a fan is `on` at boot, HA can fire a state-change event BEFORE `async_setup` finishes — the fan-listener could populate `_fan_on_rooms` before `_room_provenance` has been seeded by any mmwave/motion event.

In that window: `_compute_fan_interference_rooms` finds the fan-on room but the room's `_room_provenance` is `{mmwave: False, motion: False, ...}` (the default seed). The "mmwave-sole" check at `_compute_fan_interference_rooms` (presence.py:2217+) filters by mmwave-sole — so an empty provenance would NOT match.

I verified this is SAFE by inspecting `_compute_fan_interference_rooms`. But the proximity of the read to live-state-update is tight enough that a future change to the suspect-detection logic could regress.

**Fix:** add an assertion (or a guard log) at the top of `_apply_fan_interference_gate`: "skip if no tracker has seen any `update_room_occupancy` call yet" — a `self._first_tick_complete: bool` flag flipped to True at the end of the first `_run_inference("startup")`. Reuse the predecessor's seed-completion sentinel if one exists.

### B-M3 — `_audit_provenance_invariants` relaxation reads `dt_util.utcnow()` inside an `except` block that swallows ALL exceptions including `KeyboardInterrupt`
**Bug class:** #20 (BLE001 over-broad except)
**File:** `presence.py:340-347` (the new try block)

```python
try:
    hold = getattr(tracker, "_fan_interference_hold_until", {}) or {}
    now = dt_util.utcnow()
except Exception:  # noqa: BLE001 — defensive
    hold = {}
    now = None
```

`getattr` + `dt_util.utcnow()` realistically only fail under catastrophic conditions (module load failure). The BLE001 noqa is documented, but `now = None` then propagates to a `hold_until > now` comparison further down which would raise `TypeError`. The fallback is not safe — it just defers the crash to the comparison.

**Fix:** if `dt_util.utcnow()` ever fails, the whole audit helper should bail. Replace the inner `except` with: bail out of the loop (set `hold = {}` only, leave `now` assigned via a fallback or skip the loop entirely).

### B-M4 — `binary_sensor.py` reads `_inputs` outside the block that defines it, relying on the outer `try/except` to mask `UnboundLocalError`
**Bug class:** #21 (defensive code masking real defects)
**File:** `binary_sensor.py:~489` (`_inputs.get("fan_interference_ladder", ...)`)

`_inputs` is bound ONLY inside the `if _tracker is not None:` branch (around line 444). The new D1 code at line 489 reads `_inputs.get("fan_interference_ladder", ...)` outside that conditional. If `_tracker is None` (room not yet discovered, version-skew during reload, etc.), `_inputs` is unbound and `UnboundLocalError` fires. The outer `try/except` catches it and sets the attrs to defaults — but the operator sees `"ble_corroboration_layer": "none"` even when the gate has a verdict.

**Fix:** hoist `_inputs = (getattr(_presence, "_signal_consensus_inputs", {}) or {})` to the top of the outer `try` block so it's always defined regardless of `_tracker`. Five-line change.

---

## LOW

### B-L1 — `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` has zero subscribers in the codebase
**Bug class:** Dead surface
**File:** `signals.py:118`, `presence.py:4479-4490`

The signal is emitted but no `async_dispatcher_connect` subscriber consumes it. The planning doc said NM and the diagnostic sensors would consume it — neither does. The binary_sensor instead reads `_signal_consensus_inputs["fan_interference_ladder"]` directly. The signal is dead-weight in D1. Either wire a subscriber (UI refresh trigger) or drop the dispatch and the constant. Acceptable to defer to D2 if D2 will consume it.

### B-L2 — `_fan_interference_gated_prev` is in-memory only; first tick post-restart will spuriously re-fire `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` for every currently-held room
**Bug class:** #14 + observation-only impact
**File:** `presence.py:1071-1075`

On restart, `_fan_interference_gated_prev = set()`. First post-restart `_run_inference("startup")` tick has `_room_provenance` empty so `_compute_fan_interference_rooms` returns `[]` and `gated_now = set()` and `newly_gated = set() - set() = set()`. No spurious dispatch. SAFE — but only because `_compute_fan_interference_rooms` short-circuits on empty fan-state. Document this dependency in the field's comment so a future change doesn't break it.

### B-L3 — `set_fan_interference_hold_s` does not refresh existing hold expiries when value is decreased
**Bug class:** Surprise semantics
**File:** `presence.py:4916-4939`

Documented behavior: "Idempotent — does not refresh existing hold expiries (those use the value live at apply-tick); only future `_apply_fan_interference_gate` calls pick up the new value." This is correct, but if the operator drops the slider from 1800s to 60s expecting "all current holds expire faster," they'll be surprised. Add a docstring caveat or, better, eagerly clamp all `_fan_interference_hold_until[room]` to `now + clamped` when value decreases.

---

## Verdict on the AUDIT doc's ripple-GREEN claim

**Upheld.** Twelve consumers re-traced independently. The truth-preserving invariant is correctly enforced at a single point (the `_room_occupied` property's short-circuit OR), and no consumer can fabricate a false-unoccupied. The hold can only EXTEND occupancy, never shorten it — verified by reading the property, by tracing `_derived_mode`/`tracker.mode`/`check_zone_occupancy_confidence`/HVAC defer gate/compliance/safety/`_run_inference` independently.

**Caveat (B-H3):** the AUDIT doc marks `log_zone_event` SAFE. I disagree — it's operationally LOSSY (hold-extended rooms are indistinguishable from genuinely-occupied rooms in the DB log). Not a regression in URA's RUNTIME behavior, but a degradation in forensic surface. Operator should decide whether to fix in D1 or accept the lossy log for D1 and patch in D2.

**Restart resilience:** in-memory `_fan_interference_hold_until` reset on restart is SAFE — the room simply re-evaluates from live provenance the next tick. No spurious dispatch (B-L2). The MUST-FIX for restart is B-H1 (the operator-configured hold-seconds value).

## Must-fix before deploy

1. **B-H1** — wire `CONF_FAN_INTERFERENCE_HOLD_S` read at `PresenceCoordinator.__init__` from entry.options + mirror operator-set value back to entry.options.
2. **B-H2** — hoist the dispatch imports to module top.
3. **B-H3** — distinguish hold-extended rooms in `log_zone_event` (or document the lossy semantic as accepted-debt).

Everything else can land in fix-up or defer to D2.

## Fix-up status (Tier 2-DB fix-up pass)

| ID | Severity | Status | Notes |
|---|---|---|---|
| B-H1 | HIGH | **FIXED** | `PresenceCoordinator.__init__` (~`presence.py:1063`) now reads `CONF_FAN_INTERFERENCE_HOLD_S` from the Coordinator-Manager entry.options (falling back to `DEFAULT_FAN_INTERFERENCE_HOLD_S`, range-clamped 60-1800). `FanInterferenceHoldNumber.async_set_native_value` (`number.py:~2285`) mirrors the operator value back to CM entry.options via `hass.config_entries.async_update_entry` — the same URA-mirror pattern used by `DynamicPresetDwellMinutesNumber` and `DynamicPresetHysteresisFNumber`. Restore-from-backup / fresh-install paths now re-seed at the operator's value, not the hard-coded 300s. |
| B-H2 | HIGH | **FIXED** | `async_dispatcher_send`, `SIGNAL_FAN_INTERFERENCE_GATE_FIRED`, and `SIGNAL_PRESENCE_ENTITIES_UPDATE` hoisted to module top alongside the existing `from .signals import ...` block. Both dispatch sites (`presence.py:~4477` and `~4600`) now use the hoisted symbols. Per-tick import dict-lookup eliminated. Dispatch-side exception log demoted to WARNING (still best-effort, but visible at default log level). |
| B-H3 | HIGH | **FIXED** | `log_zone_event` payload at `presence.py:~4582` now builds `tagged_rooms` by checking each occupied room's provenance OR — when the OR is False but the derived view is True (= hold-extended), the room name is prefixed with `"(hold) "` in the persisted `rooms` list. Forensics queries can join on the prefix. Cheap implementation: no new DAO/table (deferred D2). |
| B-M1 | MEDIUM | **FIXED** | Added `_adjacency_cache: Optional[Dict[str, List[str]]]` field, `_rebuild_adjacency_cache()` + `_invalidate_adjacency_cache()` methods, rebuild call at end of `_discover_zones` and invalidation at start of `_discover_room_sensors`. Gate at `~`presence.py:2657`` now reads the cache O(1) (lazy-init on first call so test paths without discovery still work). |
| B-M2 | MEDIUM | **DEFERRED** | First-tick-post-restart safety — Reviewer verified the existing code path is SAFE (empty `_fan_on_rooms` short-circuits the gate). Added an assertion / `_first_tick_complete` sentinel would be belt-and-braces; not a current defect, deferred to a future cycle. |
| B-M3 | MEDIUM | **FIXED** | `_audit_provenance_invariants` now bails out of Invariant 1 with an explicit diagnostic entry instead of silently flagging every hold-extended room when `dt_util.utcnow()` raises (the `now=None` propagation that would have flipped the comparison). |
| B-M4 | MEDIUM | **DEFERRED** | `binary_sensor.py` `_inputs` hoist — not touched in this fix-up pass; defect is contained behind the outer `try/except` (operator sees `"none"` rather than the gate verdict in the version-skew window). Will be addressed in a focused binary_sensor pass. |
| B-L1 | LOW | **DEFERRED** | `SIGNAL_FAN_INTERFERENCE_GATE_FIRED` has zero subscribers — expected; subscriber arrives with D2 / future diagnostic sensor. Per the task spec's defer list. |
| B-L2 | LOW | **DEFERRED** | First-tick-post-restart spurious re-fire — verified SAFE in the review; comment-only documentation deferred. |
| B-L3 | LOW | **FIXED** | Same as H-A3 — slider drop now clamps existing expiries. |
