# Review A — Data Integrity + Existing-Reader Preservation

**Cycle:** presence provenance-split + fan-interference diagnostic
**Branch:** `feature/presence-provenance-split` (tip `b7701d5`, off develop `51a3d72`)
**Reviewer:** A (DATA INTEGRITY + EXISTING-READER PRESERVATION)
**Date:** 2026-06-03

---

## Scope of this review

Per Tier 2-DB (operator-elevated) charter, this frame covers:

1. **Derived-property mutation hazard** — every read/mutate site of `_room_occupied`
2. **`zone_events` DB write preservation** — `log_zone_event` row shape and content
3. **Consensus arithmetic preservation** — `tier1_occupied_count` ≡ pre-split `mmwave_occupied_count`; back-compat alias correctness
4. **Existing-reader preservation** — every consumer of `_room_occupied` / `raw_occupied` / consensus dict still gets equivalent values

Reviewers B (migration correctness + signal chain) and C (new surfaces + test authority) cover their frames.

---

## 1. Mutation-site audit for `_room_occupied`

The cycle replaces the storage attribute `_room_occupied: Dict[str, bool]` with a derived `@property` (presence.py:399-418) returning a fresh dict per access:

```python
return {room: any(bool(v) for v in kinds.values()) for room, kinds in self._room_provenance.items()}
```

Any surviving MUTATION of `_room_occupied` would now silently no-op against a throwaway dict — a CRITICAL data-integrity hazard.

**Method:** exhaustive grep across `custom_components/` and `quality/tests/` of the feature-branch worktree at `.claude/worktrees/agent-acfd903061f52a648`.

| Site | Kind | Verdict |
|---|---|---|
| `domain_coordinators/presence.py:211` (old initializer) | gone | — |
| `domain_coordinators/presence.py:313` (`occ = tracker._room_occupied`) | **read** snapshot in audit helper | SAFE |
| `domain_coordinators/presence.py:454` (`any(self._room_occupied.values())` in `_derived_mode`) | **read** | SAFE (perf note below) |
| `domain_coordinators/presence.py:644` (`"rooms": dict(self._room_occupied)` in `to_dict`) | **read** | SAFE |
| `domain_coordinators/presence.py:3808` (`any(getattr(t, "_room_occupied", {}).values())` consensus tally) | **read** | SAFE |
| `domain_coordinators/presence.py:3897` (`for rn, occ in tracker._room_occupied.items() if occ` → zone_events write) | **read** | SAFE |
| `quality/tests/test_presence_provenance_split.py:50–130` | **read** (asserts) | SAFE |
| `quality/tests/test_v47181_sleep_wake_deadlock.py:570,640` | **comment + read** | SAFE |

**Mutation hits found in non-test code: ZERO.** All historical write sites either (a) flow through `update_room_occupancy(...)` (which writes to `_room_provenance`), or (b) were the eliminated `self._room_occupied[room_name] = occupied` at the old line 318 (now removed).

`person_coordinator.py` references `_is_room_occupied` / `_get_room_occupied_time` — different methods on PersonCoordinator, not the tracker dict.
`hvac.py`, `hvac_zones.py`, `hvac_predict.py` references `any_room_occupied` — attribute on `HvacZone` (`hvac_zones.py:146`), not `ZonePresenceTracker._room_occupied`.

**Conclusion on the highest-value frame: NO surviving mutations of the derived property. The CRITICAL hazard is not realized.**

---

## 2. `zone_events` DB write preservation

`log_zone_event` DAO at `database.py:1798-1816` is **unchanged**. Row schema unchanged (`zone, timestamp, event_type, room_count, rooms`). Index unchanged (`zone_events(zone, timestamp)`).

Caller at `domain_coordinators/presence.py:3893-3906`:

```python
occupied_rooms = [rn for rn, occ in tracker._room_occupied.items() if occ]
...
db.log_zone_event(zone=zone_name, event_type=new_mode,
                  room_count=len(occupied_rooms),
                  rooms=occupied_rooms if occupied_rooms else None)
```

Pre-split: iterated the stored `Dict[str, bool]`. Post-split: iterates the derived `{room: any(provenance[room].values())}`. The boolean predicate `if occ` is identical — for any room `r`, `_room_occupied[r]` is True iff at least one kind in `_room_provenance[r]` is True, which is exactly the post-split semantic of "Tier-1 occupancy fired in this room since the last clear". **Row shape and content of `zone_events.rooms` preserved.** Existing analytics queries returning aggregations on `rooms` / `room_count` remain valid.

One legacy-call nuance: a caller that invokes `update_room_occupancy(room, True)` with `kind=None` (the back-compat path, currently exercised only by `test_v47181_sleep_wake_deadlock.py:643`) sets the sentinel `"tier1"` slot, which the derived property correctly OR-aggregates to True. The `rooms` written to `zone_events` therefore still includes that room. **SAFE.**

---

## 3. Consensus arithmetic preservation

The rename `mmwave_occupied_count` → `tier1_occupied_count` at presence.py:3795-3833:

- Pre-split tally: number of zones where `any(tracker._room_occupied.values())` is True.
- Post-split tally: same expression at presence.py:3808, against the derived view. Per §1 above the derived view is value-equivalent room-for-room.

**Per-zone, per-tick: `tier1_occupied_count` ≡ pre-split `mmwave_occupied_count`. Verified by code reading; behaviorally pinned by `quality/tests/test_presence_provenance_split.py::test_consensus_tier1_count_matches_pre_split_semantic` per the planning doc (see Review C for test-authority confirmation).**

Back-compat alias at presence.py:3873:

```python
"tier1_occupied_count": tier1_occupied_count,
"mmwave_occupied_count": mmwave_occupied_count,  # = tier1_occupied_count (line 3833)
```

Both keys carry the same int in the same tick. **Any external sensor / dashboard / NM consumer reading the old key continues to receive an identical value.** The cycle plans to retire the old key in a future version — that retirement is OUT OF SCOPE here; this review only verifies the alias is correct, which it is.

Mixed-sensor rooms (motion-on, mmwave-off) — pre-split, a single PIR firing would set `_room_occupied[r] = True` and the zone counted toward `mmwave_occupied_count` (the name was always a misnomer). Post-split, the same single PIR firing sets `_room_provenance[r]["motion"] = True` and the derived `_room_occupied[r] = True`, so the zone still counts toward `tier1_occupied_count`. **No regression on mixed-sensor counting.**

Other consensus terms (`camera_occupied_count`, `any_stale_or_lost_tracker`, `state_confidence`, the four `-0.4/-0.2/-0.15/-0.1` decrements) are arithmetically unchanged.

---

## 4. Existing-reader enumeration

| Consumer | Reads | Equivalence post-split |
|---|---|---|
| `_derived_mode` Tier-1 check (presence.py:454) | `any(self._room_occupied.values())` | Identical truth value (derived OR over kinds) |
| `to_dict` serializer (presence.py:644) | `dict(self._room_occupied)` | Same `{room: bool}` shape; sidecar `rooms_provenance` is ADDITIVE |
| `zone_events` write (presence.py:3897) | `.items() if occ` filter | Same room list |
| `_signal_consensus_inputs.tier1_occupied_count` (presence.py:3872) | tally | Identical (see §3) |
| `_signal_consensus_inputs.mmwave_occupied_count` (presence.py:3873) | alias = same tally | Identical |
| `_signal_consensus` decrement #3 (presence.py:3854) | `mmwave_occupied_count == 0` | Identical (uses local alias = `tier1_occupied_count`) |
| `raw_occupied` property (presence.py:430) | `_derived_mode == OCCUPIED` | Identical (derived from same OR) |
| `_audit_provenance_invariants` (presence.py:313) | snapshot | Read-only, safe |
| `test_v47181_sleep_wake_deadlock.py` raw_occupied tests | read | All still pass with the legacy `kind=None` path |
| `test_hvac_zone_intelligence.py` `any_room_occupied` (×~23 sites) | reads `HvacZone.any_room_occupied` — DIFFERENT attribute | UNAFFECTED by this cycle |

No consumer of `_room_occupied` / `raw_occupied` / the consensus keys is broken. **Existing-reader preservation: CLEAN.**

---

## Findings

### A.1 — LOW — Perf footnote on derived-property allocations

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py:399-418`, called from line 454 inside `_derived_mode`.
**Bug class:** Performance / allocation churn (not a documented class in QUALITY_CONTEXT.md).
**Detail:** Every read of `tracker._room_occupied` allocates a fresh dict via the comprehension. `_derived_mode` is called from `mode`, `raw_occupied`, and indirectly from at least 4 sites in `_run_inference` per tick per zone. With N zones × M rooms per zone, that's an O(N·M) dict allocation per tick where pre-split it was a stored-attribute read. This is observation-only at today's scale (~10 zones × ~3 rooms = trivial), but the audit helper at line 313 already captures the snapshot once for that reason — propagating that idiom to `_derived_mode` would be cheap and worth it if the run-tick budget ever tightens.
**Suggested fix:** Cache the derived view per `_run_inference` cycle, OR change `_derived_mode` to read `_room_provenance` directly with `any(any(v.values()) for v in self._room_provenance.values())`. Not blocking.

### A.2 — LOW — Per-kind breakdown undercounts legacy "tier1" sentinel rooms

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py:3810-3817` (also sensor.py:3947).
**Bug class:** Diagnostic / observability gap (not data-integrity).
**Detail:** `tier1_provenance_breakdown[zone][kind]` iterates only `TIER1_KINDS = ("motion","mmwave","occupancy")`. Rooms whose entries were written via the legacy `kind=None` path (sentinel slot `"tier1"`) are correctly tallied in `tier1_occupied_count` (the OR sees the sentinel) but contribute ZERO to any per-kind bucket. Today no production caller uses the legacy path (both seed and live use `_classify_entity_kind`), so the impact is zero in shipped code — but a future caller that forgets `kind=...` would silently disappear from the per-kind breakdown sensor while still showing up in the aggregate. Add a `"unknown"` bucket or assert-log when the sentinel is encountered.
**Suggested fix:** Add a `"tier1": int` slot in the bucket initialization OR emit a debug log when `_classify_entity_kind` falls through to substring and resolves to one of the three kinds (so the divergence is visible). Not blocking.

### A.3 — INFORMATIONAL — Semantic strengthening of `occupied=False` collapse

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py:553-566`.
**Bug class:** Audit Appendix A.6 #4 self-disclosed semantic improvement.
**Detail:** Pre-split, `update_room_occupancy(room, False)` did `_room_occupied[room] = False` — a last-writer-wins per-room boolean. Post-split, it clears ALL kinds for the room, which is correct under the OR semantic but is STRICTLY STRONGER than the prior bool (a room with `motion=True` then `mmwave=False` reported True before AND reports True after — same outcome — but the audit doc correctly notes that any pathological caller relying on per-room writes overriding each other would observe a behavior change). The audit doc owns this; no behavioral consumer is affected because there is no per-kind off-edge in today's discovery path (the state-change callback only knows the entity, not the type, and the prior path also did a full-room clear semantically — there's only one `entity_id` per `(room, kind)` slot in practice).
**Verdict:** Documented; not a regression.

### A.4 — INFORMATIONAL — `_has_sensors=True` on every `update_room_occupancy` call (including False)

**File:** `custom_components/universal_room_automation/domain_coordinators/presence.py:541-542 and 567-568`.
**Detail:** Behavior preserved from pre-split (old line 320-321 also set `_has_sensors=True` unconditionally inside the `if room_name in self.room_names:` guard). **No regression.**

---

## Summary stats

| Severity | Count | Notes |
|---|---|---|
| CRITICAL | 0 | Mutation hazard searched exhaustively; ZERO surviving mutate sites |
| HIGH | 0 | |
| MEDIUM | 0 | |
| LOW | 2 | A.1 perf, A.2 diagnostic undercount |
| INFORMATIONAL | 2 | A.3 documented semantic strengthening, A.4 preserved behavior |

| Frame check | Result |
|---|---|
| Derived-property mutation hazard | NOT REALIZED — 0 mutation sites surviving |
| `zone_events` row shape preserved | YES — DAO untouched, caller writes identical room list |
| `tier1_occupied_count` ≡ pre-split `mmwave_occupied_count` | YES — same expression, same predicate |
| Back-compat alias correct | YES — same tick, same int |
| Mixed-sensor (motion-on, mmwave-off) rooms counted identically | YES — derived OR still fires |
| Existing-reader enumeration | CLEAN — no consumer broken |

---

## Bug-class frequency (QUALITY_CONTEXT.md mapping)

| Bug class | Hits this review |
|---|---|
| (none) — no quality_context class triggered in this frame | — |

The two LOW findings are perf / diagnostic and do not map to an existing class. The cycle's audit doc enumerated invariant checks that this reviewer confirmed.

---

## Verdict

**SHIP** from a data-integrity perspective.

The single highest-value check — "did anyone leave a `self._room_occupied[...] = ...` site behind after the derived-property conversion" — comes back clean: ZERO surviving mutation sites across `custom_components/` and `quality/tests/`. `zone_events` row shape is unchanged. The consensus rename plus back-compat alias preserves arithmetic identity. Every enumerated consumer reads an equivalent value post-split.

The two LOW findings (A.1 perf, A.2 per-kind diagnostic undercount) are non-blocking and can be deferred or fixed in-cycle per the operator's "Fix LOWs In-Cycle" rule. Recommend fixing A.2 (~5 LoC) to harden the future-caller story; A.1 can wait until tick-budget pressure emerges.

Reviewers B and C own migration-chain and new-surface frames respectively — defer to their verdicts on signal-chain integrity and the new sensor / fan-diagnostic surfaces.
