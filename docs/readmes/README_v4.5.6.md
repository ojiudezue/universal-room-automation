# v4.5.6 — Venetian timed-close fix + cover gate cover_type awareness (Bug Class #33)

**Date:** 2026-05-08
**Type:** Tier 1 hotfix (~50 LoC + 22 regression tests)
**Predecessor:** v4.5.5
**Reproducer:** Two venetian blinds (Study A, Master Bedroom) stayed open past their configured automation time on 2026-05-08 evening.

## Summary

Closes the third hit of the **CONF_COVER_TYPE dead-config class**, in a sibling helper that v4.5.0.4 missed. v4.5.0.4 made the dispatcher (`_send_covers_with_verify`) and the verify path (`_cover_at_target`) tilt-aware, but the gate helpers `_are_covers_already_open` / `_are_covers_already_closed` still compared on `state.state`. For a venetian blind with `position=0` (blind lowered) and `tilt_position=97` (slats wide open), the entity reports `state="closed"` — so the gate returned True and the timed-close runner silently skipped, leaving slats open all evening.

Same root cause as v4.5.0.4. Different cousin site. Documented as Bug Class #33 to prevent the next recurrence.

## Root cause

**Live evidence from history at the time of the report:**

| Entity | state | position | tilt_position |
|---|---|---|---|
| `cover.study_a_blinds` | `closed` | 0 | **97** ← slats wide open |
| `cover.mb_shade` | `closed` | 0 | **100** ← slats fully open |

`automation.py:check_timed_cover_close` (line 1281, pre-v4.5.6):

```python
if not self._is_cover_close_time(now):
    return

# Respect manual override: skip if already closed
if self._are_covers_already_closed():   # ← returns True for tilt=97
    self._last_timed_close_date = today  # ← marks "fired today"
    return
```

`_are_covers_already_closed()` only checked `state.state != "closed"`. For tilt blinds with the entity state driven by position (not tilt), this gate fired wrong → schedule skipped → user's blinds stayed open.

The dispatcher (which IS tilt-aware after v4.5.0.4) never got called.

## Fix

Two-part fix that closes both the immediate symptom and the broader bug class:

### Part 1 — Drop the gate from the deterministic timed paths

Both `check_timed_cover_open` (line 1153) and `check_timed_cover_close` (line 1281) used to early-return when the gate said "already in target state." Removed both calls.

**Rationale:** A timed close at sunset is a *deterministic schedule* — it should fire whether or not the blinds *look* in-target. The verify path (`_cover_at_target`) resolves a no-op close on already-closed slats in zero retries, and `cover.close_cover_tilt` on already-closed slats is idempotent. Cost is one extra service call per day per room. Removes a whole class of "gate disagrees with dispatch/verify at the boundary" bugs.

### Part 2 — Make the gate helpers cover_type-aware (for entry/exit paths)

The entry/exit cover helpers fire many times per occupancy event, so the gate's dedup is genuinely useful there — kept the gate but made it tilt-aware:

```python
def _are_covers_already_closed(self) -> bool:
    available = self._get_available_covers()
    if not available:
        return True
    cover_type = self.config.get(CONF_COVER_TYPE, COVER_TYPE_SHADE)
    for cover_id in available:
        state = self.hass.states.get(cover_id)
        if state is None:
            return False
        if cover_type == COVER_TYPE_TILT:
            tilt = state.attributes.get("current_tilt_position")
            if tilt is None:
                if state.state != "closed":
                    return False
                continue
            try:
                if float(tilt) > 5.0:
                    return False
            except (TypeError, ValueError):
                if state.state != "closed":
                    return False
        else:
            if state.state != "closed":
                return False
    return True
```

Mirror for `_are_covers_already_open` — tilt path checks `tilt >= 95.0`. Thresholds (≤5 / ≥95) match the verify path's `_cover_at_target` so all four cover helpers (dispatch, verify, gate-closed, gate-open) agree on the same "closed" / "open" semantics for tilt blinds.

Defensive fallback: when `current_tilt_position` attribute is missing (some integrations don't expose it), falls back to `state.state` comparison — preserves pre-v4.5.6 behavior for those edge cases.

## Bug Class #33 — Partial Fix: Sibling Helpers Skipped

Logged in `docs/QUALITY_CONTEXT.md` as a new bug class. Pattern: a config-honored fix threads the runtime branch through one or two sites (the obvious ones from the user's symptom) but misses cousin sites that also depend on the same field. Subtype of #32 (Form Field With No Runtime Reader): the reader was added, just not in **all** the places it conceptually needs to live.

**Prevention checklist** (added to QUALITY_CONTEXT.md):
- When fixing a config-honored-vs-not bug, search the same domain for other helpers making a same-shape decision on the competing attribute.
- Reviewer mandate: a PR description that names only one or two sites for a CONF_X plumb-through is a yellow flag.
- Lean on the verify path's thresholds when a gate or pre-check makes the same decision — disagreement at boundaries produces subtle bugs.
- Prefer dropping the gate for deterministic schedules when the dispatcher's no-op cost is low.

## What this DOES NOT do

- Doesn't change anything for shade-type rooms (the dominant case) — every shade-path code path is byte-equivalent to v4.5.5.
- Doesn't add per-blind tilt position control (still slats fully open / fully closed via `cover.{open,close}_cover_tilt`).
- Doesn't change verify-path semantics — the v4.5.0.4 thresholds are reused so all four helpers stay in lockstep.
- Doesn't touch HVAC-driven cover actions (`domain_coordinators/hvac_covers.py`) — out of scope, would benefit from the same audit if HVAC-managed venetian blinds become common.

## Tier 1 Review

| Severity | Finding | Resolution |
|---|---|---|
| (no CRITICAL) | — | — |
| HIGH | Gate helpers were a sibling site of the v4.5.0.4 fix and silently skipped the timed close for tilt blinds | Fixed: gate is cover_type-aware AND removed from the deterministic timed paths |
| MEDIUM | Cousin-site bug class wasn't documented; same shape could recur the next time a `CONF_X` gets a runtime branch | **Documented as Bug Class #33** in QUALITY_CONTEXT.md with detection & prevention |
| LOW | The `_are_covers_already_*` helpers each grow ~25 LoC | Acceptable; matches the v4.5.0.4 verify path's structure for symmetry |

**Verdict: READY TO DEPLOY.**

## Tests

22 new tests in `quality/tests/test_v456_cover_gate_tilt.py`:

- **Shade unchanged (2):** `_are_covers_already_closed` shade path is byte-equivalent to pre-v4.5.6.
- **Tilt-aware closed gate (7):** the user reproducer (tilt=97 → not closed); thresholds at exactly 0/5/6/50; no-tilt-attr fallback; invalid-tilt fallback.
- **Tilt-aware open gate (5):** mirror for `_are_covers_already_open`; threshold at 95/94; the inverse-position case (Master Bedroom shape).
- **Edge cases (4):** empty cover list, missing state, multi-cover all-closed, multi-cover one-open.
- **Source contract (4):** gate helpers must read `CONF_COVER_TYPE` and `current_tilt_position`; timed-close/open must NOT call the respective gate; entry/exit paths still use the gate (exactly 1 call site each).

Mirror-style — same pattern as v4.5.0.4 + v4.5.3 + v4.5.5 (factory's helpers aren't cleanly importable without HA core).

**Test count progression:**
- v4.5.5: 1956 tests, 0 isolated failures across 53 files
- **v4.5.6: 1978** (+22), 0 isolated failures across 54 files

## Live validation (post-restart)

For Study A and Master Bedroom (the user's reproducer):

1. After HACS download + HA restart, set both blinds to position=0 + tilt=open (the pre-fix bad state) by hand.
2. Wait for the next configured close time (or trigger via the room's reload button).
3. **Pre-v4.5.6:** runner skipped, slats stayed open, log shows nothing.
4. **Post-v4.5.6:** runner fires `cover.close_cover_tilt` against the room's covers, verify confirms `current_tilt_position ≤ 5`, log shows `Timed cover close [Study A]: closing N cover(s)`.
5. Re-trigger immediately: runner fires again (no gate), verify confirms still ≤ 5, no retries needed (zero-cost no-op). Log shows the second invocation.

For shade rooms (the dominant case): no behavior change expected. Spot-check one room to confirm.

## Deploy notes

- No DB schema changes
- No migration needed
- HACS download required after deploy.sh
- HA restart required (automation.py is in the loaded integration package)

## Next

- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation
- **Sensor Health Surfacing** (backlog) — chattering + stuck-on detection per the 2026-05-08 Kitchen mmWave investigation
- **CM cleanup cycle** — `CONF_MUSIC_FOLLOWING_ENABLED` + `CONF_COMFORT_ENABLED` + the unused `"comfort"` slot in `COORDINATOR_ENABLED_KEYS`
- **HVAC covers audit** — verify `domain_coordinators/hvac_covers.py` doesn't have its own cover_type-blind sites
