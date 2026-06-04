# Review C — New Surfaces + Test-Fixture Authority + Observation-Only Guarantee

**Cycle:** Presence provenance-split + fan-interference diagnostic
**Branch:** `feature/presence-provenance-split` (tip `b7701d5`, off `develop` `51a3d72`)
**Reviewer frame:** new sensor/binary-sensor attribute surfaces (D5), test-fixture authority across 6 new modules + harness, the single modified pre-existing test, listener-lifecycle of the D3 fan hook, and — highest value — the observation-only guarantee on the fan-interference primitive.
**Verdict:** **SHIP** — observation-only guarantee proven, test-fixture authority sound (one tautology + one regression-blinded loosening flagged for follow-up). No CRITICAL findings.

---

## Summary statistics

| Severity | Count | Status |
| --- | --- | --- |
| CRITICAL | 0 | — |
| HIGH | 1 | Recommend fix in-cycle (test-loosening too loose) |
| MEDIUM | 2 | Recommend fix in-cycle |
| LOW | 2 | Defer or fix in-cycle per "fix LOWs in-cycle" rule |

---

## OBSERVATION-ONLY GUARANTEE — verified GREEN

The single highest-value question: does anything the cycle introduces feed a veto, gate, mode-output, consensus delta, or actuation?

**Method.** Repo-wide `git grep` against `feature/presence-provenance-split` for every new symbol:

- `fan_interference_active` / `fan_interference_rooms` / `fan_interference_suspect`
- `_fan_on_rooms`
- `tier1_provenance_breakdown` / `tier1_occupied_count`

**Findings.**

1. `fan_interference_*` keys appear ONLY in `sensor.py:3876-3895` (read-into-attrs) and `binary_sensor.py:425-436` (read-into-attrs). Zero references in `domain_coordinators/hvac*.py`, `domain_coordinators/safety.py`, `domain_coordinators/house_state.py`, `aggregation.py`, or any actuation module. Confirmed via `git grep "fan_interference" feature/presence-provenance-split -- custom_components/`.
2. `_fan_on_rooms` is written only by `_discover_room_fans` (presence.py:1942-1930) and `_handle_fan_change` (presence.py:1987-1989); read only by `_compute_fan_interference_rooms` (presence.py:2060), `sensor.py:3885` (display), `binary_sensor.py:424` (display), and the tracker's own diagnostic dump (presence.py:654). NO consensus / inference / actuation consumer.
3. `tier1_occupied_count` in `signal_consensus_inputs` is set to the SAME value as the pre-cycle `mmwave_occupied_count` (presence.py:3833 explicit alias). The consensus delta (`if camera_occupied_count > 0 and mmwave_occupied_count == 0: consensus -= 0.15` at presence.py:3854) reads the SAME numerical value as pre-cycle — `any(_room_occupied.values())` summed across trackers. Consensus arithmetic byte-equivalent.
4. `_room_occupied` is now a `@property` (presence.py:399-417) returning `{room: any(provenance[room].values())}`. Per `_audit_provenance_invariants` (lines 269-323 of presence.py), this is equivalence-preserving versus the pre-cycle storage attr in every consumer surveyed in `AUDIT_presence_provenance.md` Appendix A.2. **One semantic widening** worth flagging: pre-cycle `update_room_occupancy("a", True)` overwrote the bool to True; the new code adds a sentinel `"tier1"` slot. Repeat calls with `kind=None` are idempotent — fine. Pre-cycle behavior was last-writer-wins; new is strictly stronger (OR across kinds). This matches the audit's documented "semantic improvement, not regression" framing.

**Conclusion.** Observation-only guarantee holds. No actuation surface contaminated.

---

## Findings

### HIGH-1 — `test_v47181_sleep_wake_deadlock.py::test_room_sensor_seed_block_present` loosening is too loose (regression-blinding)
**File / line.** `quality/tests/test_v47181_sleep_wake_deadlock.py:591-600`
**Bug class.** #40 — Self-Validating Behavioral Tests (degenerate variant: assertion that is satisfied by any plausibly-adjacent code).
**Severity.** HIGH (this is the regression guard for the v4.7.18.1 boot-seed fix — load-bearing).
**What changed.** The previous assertion `assert "tracker.update_room_occupancy(room_name, occupied)" in body` was replaced with the pair `assert "tracker.update_room_occupancy(" in body` + `assert "room_name" in body and "occupied" in body`. The justification — accommodating the new optional `kind=` kwarg — is sound, but the new assertions don't pin the call shape. `"room_name"` and `"occupied"` appear throughout `_discover_room_sensors` as local-variable names independently of the call site. A future edit that hard-codes a literal (e.g. `tracker.update_room_occupancy(room_name, False, kind=kind)`) or accidentally passes a different variable would still satisfy both substring checks.
**Fix.** Replace the loosened pair with a regex that pins the call shape:
```python
import re
assert re.search(
    r"tracker\.update_room_occupancy\(\s*room_name\s*,\s*occupied(?:\s*,\s*kind=\w+)?\s*\)",
    body,
), "v4.7.18.1 fix-up: room-sensor seed must call update_room_occupancy(room_name, occupied[, kind=...])"
```
This preserves the relaxation for the new optional kwarg while keeping the regression guard tight.

### MED-1 — `test_signal_consensus_inputs_additive_only` is a tautology (does not exercise production code)
**File / line.** `quality/tests/test_presence_provenance_split.py:225-258`
**Bug class.** #40 — Self-Validating Behavioral Tests.
**Issue.** The test synthesizes a literal dict (`sample_dict = {...}`) with the keys the cycle intends to publish and asserts the synthesized dict has those keys. The production `_run_inference` code path that ACTUALLY builds `self._signal_consensus_inputs` (presence.py:3860-3884) is never invoked. If a future edit removes `"fan_interference_active"` from the production dict, this test still passes.
**Fix.** Either (a) invoke `_run_inference` against a tracker-staged coordinator and assert `set(coord._signal_consensus_inputs.keys())` matches the expected key-set, or (b) downgrade the test to a source-grep canary asserting each key literal appears inside the `_signal_consensus_inputs = {...}` block in `presence.py`. Option (b) is the cheaper path and is consistent with the other source-grep tests in `test_presence_provenance_surface.py`.

### MED-2 — `_compute_fan_interference_rooms` short-reads `_room_provenance` BEFORE it has been refreshed by the listener
**File / line.** `custom_components/universal_room_automation/domain_coordinators/presence.py:2055-2092`
**Bug class.** #14 — Config Snapshot Staleness (variant: per-tick read-once-vs-mutated-mid-tick).
**Severity.** MEDIUM (observation-only — worst case is one tick of stale `fan_interference_rooms` output; no actuation impact).
**Issue.** The helper iterates `tracker._room_provenance.get(room_name, {})` directly. Because the D3 fan-change handler runs OUTSIDE the inference cadence and writes only `_fan_on_rooms` (not `_room_provenance`), there's no race here for fans. BUT: occupancy state-change events DO write `_room_provenance` via `_handle_occupancy_change`, and they call `async_create_task(self._run_inference("occupancy_change"))` (presence.py:2386). If two occupancy events fire near-simultaneously with the periodic `_run_inference` tick, the helper could read partially-updated `_room_provenance` (one room's mmwave slot True, another's not yet flipped). This is documented HA-callback-scheduling behavior — not a CRITICAL bug because the consensus arithmetic is unaffected. Worth noting in the docstring or accepting as known limitation.
**Fix (optional).** Add one sentence to the docstring: "Per-tick observation: `_room_provenance` reads may be one-listener-event behind; this is acceptable because the primitive is diagnostic and the next tick reconciles."

### LOW-1 — `binary_sensor.py` D5 attr block silently swallows ALL exceptions
**File / line.** `binary_sensor.py:437-443`
**Bug class.** None directly — observability hazard.
**Issue.** The `except Exception:` at line 437 catches anything (KeyError, AttributeError, but also `asyncio.CancelledError` on shutdown — though `extra_state_attributes` is sync, so cancellation is unlikely here). A coordinator API change (e.g. `provenance_for` being renamed) would silently fall back to all-False without logging. The function-local fallback re-imports `TIER1_KINDS` and sets defaults. Good defensive behavior, but no `_LOGGER.debug(..., exc_info=True)` means operators will never see WHY their dashboard shows all-False.
**Fix.** Add `_LOGGER.debug("D5 attr derivation failed for %s", self.entity_id, exc_info=True)` inside the except branch.

### LOW-2 — `_zone_provenance_breakdown` and `_signal_consensus_get_list` silently swallow exceptions
**File / line.** `sensor.py:3949-3953`, `sensor.py:3962-3966`
**Bug class.** None directly — observability hazard.
**Issue.** Same as LOW-1 — bare `except Exception` returns empty/zero dict/list without any log line. For a diagnostic surface this is intentionally lenient, but a misnamed attribute will fail silently forever.
**Fix.** One-line `_LOGGER.debug(..., exc_info=True)` per branch.

---

## Source-grep canary tests — adequate, no findings

- `test_presence_provenance_surface.py` asserts the four D5 attr-name literals + the two zone-rollup literals exist in the production source. Reads `binary_sensor.py` / `sensor.py` from disk via `open()` — independent of import, so the test is a true source canary, not a tautology. SOUND.
- `test_no_new_entity_classes_introduced_by_d5` walks the AST of `binary_sensor.py` / `sensor.py` and asserts no class names contain `"Provenance"` or `"FanInterference"`. Good structural guardrail. SOUND.
- `test_attrs_refresh_via_existing_signal` asserts no new dispatcher signal name contains `"PROVENANCE"` or `"FAN_INTERFERENCE"`. Good additive-only check. SOUND.
- `test_d3_docstring_meets_obligation` enforces the D7 research-handoff documentation contract (≥10 lines, four key phrases). SOUND.

## D3 listener lifecycle — verified

`async_track_state_change_event` registration at `presence.py:1942` appends to `self._unsub_listeners`. `BaseCoordinator.async_unload` (base.py:284-286) iterates `_unsub_listeners` and calls each. `test_listener_lifecycle_unregister_on_reload` in `test_presence_fan_interference_layer1.py` asserts `len(coord._unsub_listeners) == 1` after `_discover_room_fans()`. Lifecycle bookkeeping is correct.

## D5 attribute round-trip + serialization — verified

- `fan_interference_rooms` is set/sorted-list in both attr surfaces (`sensor.py:3876-3884`, `presence.py:3878`). No set leaks into HA state attrs.
- `tier1_provenance` is `dict[str, bool]`, `last_kind_to_fire` is `str`, `fan_on` and `fan_interference_suspect` are `bool` — all JSON-serializable.
- `tier1_provenance_breakdown` is `dict[str, int]` — JSON-clean.
- `fan_on_rooms` in the zone rollup is `sorted(set)` -> list — JSON-clean.
- No new RestoreEntity coupling — derived per-tick reads only.

## QUALITY_CONTEXT bug-class touchpoints

| Bug class | Touched | Verdict |
| --- | --- | --- |
| #1 Coordinator Lifecycle Confusion | D3 listener registration | OK — uses `_unsub_listeners`; teardown verified |
| #34 Function-Local Import | `binary_sensor.py:402`, `sensor.py:3940` | OK — explicitly cited in comments as Bug Class #34 doctrine |
| #38 Discarded `async_listen` Unsubscribe | D3 listener | OK — unsub appended to `_unsub_listeners` |
| #40 Self-Validating Behavioral Tests | HIGH-1, MED-1 | FLAGGED — fix recommended |

## Verdict

**SHIP — fix HIGH-1 (regression-blinded test loosening) in-cycle. MED-1 / MED-2 / LOW-1 / LOW-2 are quality improvements compatible with the operator's "fix LOWs in-cycle" rule when bandwidth allows.**

The observation-only guarantee is rock-solid: every new symbol traces only to display surfaces. Test-fixture authority is largely sound — most tests drive real production code (`ZonePresenceTracker`, `_classify_entity_kind`, `_compute_fan_interference_rooms`, `_audit_provenance_invariants`); the source-grep canaries are legitimate canaries (asserting against production source on disk). The two test issues (HIGH-1 + MED-1) are the visible cracks; both are surgical fixes (~10 lines total).
