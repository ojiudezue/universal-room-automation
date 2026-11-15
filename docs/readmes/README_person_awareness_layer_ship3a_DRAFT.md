# Person-awareness layer ship 3a (DRAFT, not deployed)

Plan: `docs/planning/PLANNING_person_awareness_layer_ship3.md` (rev 3.4.1). Branch `feature/layer-ship3a`.
Contract: `docs/planning/CONTRACT_person_awareness_layer.md` §4.1-§4.3. State of play: presence header entry
"Person-awareness layer ship 3a". This draft carries the notes the review asked for; the full README (live criteria,
validation table) is written at deploy.

## Notes from review (fix-up round)

- **Ordering, for step 7 (review B-L3).** A listener that runs synchronously during the `ura_person_egress_event`
  bus event does not yet see that crossing in the ring (`get_crossings_since` / `get_crossing` /
  `get_last_crossing`): `_resolve_direction` fires the bus event first and stores the record second. This is
  develop's existing order (kept on purpose, plan §3 F3, §10); step 7 must not expect otherwise. The same line
  belongs in the plan's §12 write-back list (planner's branch).
- **Guard runtime (review B-L2).** `test_person_awareness_layer_guard.py` took about 26-29 s per process; memoising
  `ast.walk` per node (same nodes, same order; parsed trees and per-module scans were already cached) brings it to
  about 13 s, of which the one full real-tree scan is about 8 s. Every rule is unchanged (the exact allowlist
  match is the proof). Going under 10 s would need rule-level restructuring (the R3 taint fixed point and the
  harvest pass), not attempted.
- **`CrossingRecord.nameable` (review B-L1)** is a frozen, sorted tuple of `(slug, confidence)` pairs, default
  `()`: immutable, and `asdict` / deepcopy / pickle / hash work. G3 normalises a mapping into that shape; read it
  as `dict(record.nameable)`. No reader existed.
- **Move-log truncation (review A-L2)** also answers True for `t` older than `PERSON_LOCATION_MOVES_MAX_AGE_S`
  (those moves were pruned). Presence delegates `location_moves_since` / `location_moves_truncated_since` added
  (review A-L1).
