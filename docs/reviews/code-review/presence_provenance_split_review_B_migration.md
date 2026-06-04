# Review B — Migration Correctness + Signal-Chain Integrity

**Cycle:** Presence provenance-split + fan-interference diagnostic  
**Branch:** `feature/presence-provenance-split` (tip `b7701d5`, off develop `51a3d72`)  
**Reviewer frame:** Migration correctness + signal-chain integrity (Reviewers A and C cover correctness/edge cases and new-surfaces/test-fixture authority respectively)  
**Verdict:** **SHIP**, with one MED logged for fix-up and three LOWs for in-cycle housekeeping (per `feedback_fix_lows_in_cycle`).

---

## Scope of this frame

Per the assignment, this review answers six framing-disjoint questions:

1. Seed-vs-live classifier parity  (`_classify_entity_kind` called from both)
2. Cross-coordinator config read path (per-room `CONF_MOTION_SENSORS` / `CONF_MMWAVE_SENSORS` / `CONF_OCCUPANCY_SENSORS`)
3. Legacy `kind=None` → `"tier1"` sentinel preserves pre-split OR semantics
4. `raw_occupied` → `_derived_mode` → `_room_occupied` (now a `@property`) byte-identical to pre-split, preserving v4.7.18.1 WAKING gate
5. `mmwave_occupied_count` → `tier1_occupied_count` rename + alias, no double-emit
6. `update_room_occupancy` call-site migration completeness

I read the diff against `develop`, the feature-branch presence.py (4,282 LoC), the audit document `INVESTIGATION_presence_provenance_audit_and_fan_noise.md`, the planning doc, and the consumer files (`sensor.py`, `binary_sensor.py`, `base.py`).

---

## Findings

### B-MED-1 [MEDIUM] — Classifier doc-comment misnames the bug class
**Bug class:** N/A (terminology hygiene; touches docs)  
**File:lines:** `domain_coordinators/presence.py:213-214, 1786-1787, 2361`  
**Issue:** Three comment blocks (the module-level helper preamble, the seed loop, and `_handle_occupancy_change`) refer to "Bug Class #1 (seed-vs-live divergence)". `docs/QUALITY_CONTEXT.md` Bug Class #1 is "Coordinator Lifecycle Confusion". The intended reference is the v4.7.18.1 review finding **B-HIGH-1** (`docs/reviews/code-review/v4.7.18.1_reviewerB.md:20`), which is a *finding ID inside one review*, not a bug class. Mixing the two namespaces causes future readers to grep `QUALITY_CONTEXT.md` and find an unrelated lifecycle class.  
**Migration impact:** None to runtime behavior. Doc-only.  
**Fix:** Rephrase to "the v4.7.18.1 B-HIGH-1 hazard" (the comments already say that on the next line — just drop the leading "Bug Class #1" phrase) OR formally promote the seed-vs-live-divergence hazard to a real numbered class in `QUALITY_CONTEXT.md` (Reviewer B v4.7.18.1 already suggested this).  
**Estimated effort:** 5-10 LoC across three comment blocks.

### B-LOW-1 [LOW] — Seed loop never seeds `False` states; entity off-edges only land via live callback
**Bug class:** Pre-existing (#5 Race Conditions on Startup, adjacent)  
**File:lines:** `domain_coordinators/presence.py:1777-1779`  
**Issue:** The seed loop at `_discover_room_sensors` short-circuits with `if not occupied: continue` and never calls `update_room_occupancy(..., False, kind=...)`. Consequence: rooms whose Tier-1 entity reports "off" at boot have NO key in `_room_provenance`. The derived `_room_occupied` therefore omits them entirely (per `_room_occupied` property at `:400-419`). The Invariant 4 check in `_audit_provenance_invariants` (key-set equality) becomes vacuously true for those rooms.  
**Verification:** Inherited from v4.7.18.1 (`develop:presence.py:1509` has the identical guard). Not a regression introduced by this cycle.  
**Why kept as LOW:** byte-equivalent to pre-split behavior. Pre-split `_room_occupied` also had no entry for never-fired rooms.  
**Fix (in-cycle housekeeping, ~6 LoC):** add an `else` branch that calls `tracker.update_room_occupancy(room_name, False, kind=...)` so the room key is always present after seeding. This stabilizes the `_room_provenance.keys()` shape across all rooms and makes the new diagnostic surface (`tier1_provenance_breakdown` zone-rollup) consistent on tick 1.

### B-LOW-2 [LOW] — `_classify_entity_kind` picks first-match if duplicate room names exist
**Bug class:** N/A (defensive against config-flow reload race)  
**File:lines:** `domain_coordinators/presence.py:236-256`  
**Issue:** During a Room ConfigEntry reload, two entries with the same `CONF_ROOM_NAME` can briefly coexist (old + new). The classifier iterates `hass.config_entries.async_entries(DOMAIN)` and `break`s on the first matching `CONF_ROOM_NAME` after the membership check. If the old entry is iterated first and has different `CONF_MMWAVE_SENSORS` / `CONF_MOTION_SENSORS` lists, the classifier briefly returns the stale kind.  
**Migration impact:** None at steady state. A reload window of seconds.  
**Fix (deferrable):** prefer the entry whose `entry.state == ConfigEntryState.LOADED`, or short-circuit using the substring fallback when more than one entry matches. ~6 LoC. Defer-OK.

### B-LOW-3 [LOW] — `_classify_entity_kind` reads `entry.data` for `CONF_ENTRY_TYPE` and `CONF_ROOM_NAME` but data+options merge for the sensor lists
**Bug class:** Pre-existing pattern adjacency  
**File:lines:** `domain_coordinators/presence.py:237-248`  
**Issue:** Inconsistent merge policy. Lines 237-239 read `entry.data.get(CONF_ENTRY_TYPE)` and `entry.data.get(CONF_ROOM_NAME)` directly. Lines 244-248 do the `{**data, **options}`-style merge for sensor lists. If a future options-flow ever allows editing `CONF_ROOM_NAME` (it doesn't today; checked `config_flow.py` / `options_flow.py` not in scope of this frame), the entry-match step would miss the rename. The audit doc explicitly calls options the "canonical post-flow surface" (cycle source comment at :243).  
**Fix:** apply the same `{**data, **options}` merge for the entry-match step. Already implemented at the fan discovery path `:1444-1446` (`config = {**(entry.data or {}), **(entry.options or {})}`) — copying that pattern keeps the two new code paths consistent. ~3 LoC.

---

## Frame-by-frame verification (PASS findings)

### 1. Seed-vs-live classifier parity — PASS
- Both call sites call **the same module-level function** `_classify_entity_kind(self.hass, entity_id, room_name)` with the **same inputs**.
- Seed loop: `presence.py:1781` reads `room_name = tracker._entity_to_room.get(entity_id)` → `presence.py:1789` calls classifier.
- Live callback: `presence.py:2357` reads `room_name = tracker._entity_to_room.get(entity_id)` (identical line) → `presence.py:2362` calls classifier.
- Live name-fallback path: `presence.py:2375` calls classifier with the same shape.
- `_entity_to_room` is populated once at `register_entity` (`presence.py:620`); not mutated between seed and live. Therefore `room_name` arg is identical, classifier output is identical. **Byte-equal.**

### 2. Cross-coordinator read path — PASS
- `_classify_entity_kind` iterates `hass.config_entries.async_entries(DOMAIN)` filtered by `CONF_ENTRY_TYPE == ENTRY_TYPE_ROOM`. By `_discover_room_sensors` time, room entries are already loaded (the build_room_area_map at `presence.py:1451` and `_discover_zones` at `:1454` succeed only when entries are loaded — see comment at `:1447-1449`).
- For the live callback, entities only register via `tracker.register_entity` at `:1741`, which runs inside `_discover_room_sensors`. By that time entries exist. Resolution holds.
- The substring fallback at `:264-270` mirrors the discovery filter at `:1709` (`occupancy_keywords = ("occupancy", "motion", "presence", "mmwave")`). Same vocabulary, fall-through to "occupancy".
- Defensive `try/except` at `:235-262` swallows config-registry errors mid-reload — falls through to substring. Safe.

### 3. Legacy `kind=None` → `"tier1"` sentinel — PASS
- `update_room_occupancy(..., kind=None, occupied=True)` writes to slot `"tier1"` (`presence.py:538`). `any(_room_provenance[room].values())` correctly returns True. Pre-split bool-OR equivalence preserved.
- `_audit_provenance_invariants` allows `"tier1"` alongside `TIER1_KINDS` (`:302, 305`). Invariant 2 holds.
- All **three in-source callers now pass `kind=` explicitly** (`presence.py:1792, 2363, 2378`). No production caller depends on the sentinel — it exists purely for tests + future external callers. Migration is complete.

### 4. `raw_occupied` → `_derived_mode` → `_room_occupied` byte-identical — PASS
- `_room_occupied` is now a `@property` (`:400-419`) returning `{room: any(bool(v) for v in kinds.values())}`. Every read site is `.values()`, `.get(...)`, or `.items()` — all read-only dict operations. Sites verified: `:454`, `:644`, `:3282`, `:3337` (note: line numbers from feature branch).
- `raw_occupied` (`:430-437`) calls `self._derived_mode`. `_derived_mode` (`:439-468`) reads `any(self._room_occupied.values())` at `:454`. The property returns a fresh dict per access (no mutation hazard). Composition chain is intact.
- The v4.7.18.1 WAKING gate at `:3118` reads `t.raw_occupied` per zone tracker — no change to the consumer; gate behavior preserved.
- The `occupied=False clears ALL kinds` rule at `:553-566` matches pre-split last-writer-wins semantics for the OR-output. The audit doc's claim that the new OR is "strictly stronger" (A.6 #4) only holds when no other kind has been set off-by-other-event; in the steady-state OR-output it equals pre-split. **No regression to the WAKING gate.**

### 5. Rename `mmwave_occupied_count` → `tier1_occupied_count` + alias — PASS
- Internal compute is `tier1_occupied_count` (`:3796, :3809, :3820`).
- Alias is assigned at `:3833`: `mmwave_occupied_count = tier1_occupied_count`.
- Both keys emitted in the dict at `:3872-3873`. Identical value within the same tick.
- Downstream consumer at `:3854` (`camera_occupied_count > 0 and mmwave_occupied_count == 0`) uses the alias — still correct because alias === canonical.
- `git grep mmwave_occupied_count feature/presence-provenance-split -- custom_components/` returns only `presence.py`. No external HVAC/sensor consumer reads the old key from anywhere outside the alias-emission site. **No double-emit, no missed migration.**

### 6. `update_room_occupancy` call-site migration — PASS
- Three production call sites, all migrated to pass `kind=` via the classifier: `:1792`, `:2363`, `:2378`. Verified by `git grep`.
- Listener cleanup: D3 fan listener appends to the inherited `BaseCoordinator._unsub_listeners` (`base.py:181, 282-286`). Cleanup symmetric with prior listeners. No leak across reload.

---

## Summary statistics

| Severity | Count | Fix in-cycle | Defer |
|---|---|---|---|
| CRITICAL | 0 | — | — |
| HIGH | 0 | — | — |
| MEDIUM | 1 (B-MED-1) | 1 | 0 |
| LOW | 3 (B-LOW-1/2/3) | 2 (B-LOW-1, B-LOW-3) | 1 (B-LOW-2) |

**Frame-disjoint bugs vs Reviewers A and C:** all four findings are at the migration / signal-chain seam. Reviewers A (correctness) and C (new surfaces + test authority) won't see them by design — A would look at edge cases, C at sensor surface and test-fixture authority.

---

## Verdict

**SHIP.** No CRITICAL/HIGH in this frame. The six migration-correctness invariants hold:

1. Seed-vs-live classifier identity is structurally enforced (same function, same args, same `_entity_to_room` map).
2. Cross-coordinator config read is timing-safe (entries loaded by `_discover_room_sensors` time).
3. Legacy back-compat sentinel preserves OR equivalence.
4. `raw_occupied` composition is byte-identical to pre-split — v4.7.18.1 WAKING gate intact.
5. Key rename has alias-equivalent value, no double-emit, no external missed consumers.
6. All in-source `update_room_occupancy` call sites pass `kind=`.

**Fix-up recommended before deploy:** B-MED-1 (doc rename, 5-10 LoC) + B-LOW-1 (seed False states, ~6 LoC) + B-LOW-3 (data+options merge consistency, ~3 LoC) — all qualify as in-cycle housekeeping per `feedback_fix_lows_in_cycle`. B-LOW-2 may defer to a follow-up cycle.

**Post-deploy live spot-check (D-level acceptance, hands off to Reviewer D):** verify within one tick post-restart that `signal_consensus_inputs["mmwave_occupied_count"] == signal_consensus_inputs["tier1_occupied_count"]`. Single check covers the entire rename-alias correctness in production.
