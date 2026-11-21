# Review: fix/s1-anchor-reasons (0784d7d15 + 07d205532)

Card EGRESS-DIRECTION-AWARE-IDENTITY-1. One pass, framing A (correctness and edge cases) plus a light B pass (lifecycle and persisted shape). Reviewed 2026-11-20.

## Merge check
- merge-base 9e171ad99. develop has moved 33 commits since then, touching `security_lock_freshness.py`, `perimeter_alert.py`, docs, kanban and tests. None of those files overlap with the 7 files this branch changes.
- `git merge-tree --write-tree develop fix/s1-anchor-reasons` gives a clean tree (3edf07469). No conflicts.

## Identity model
- The change consumes F3 (door crossing and identity attach from EgressDirectionTracker) and F1 (the person's own counted arrival edges from the presence ledger, `get_person_edges_since`).
- It produces notification text only: "arrived" vs "came in". The diagnostic reason and counter it adds are display-only.
- Consumer class is notification naming. The ≥0.75 gate is unchanged (`transit_validator.py` `_arrival_departure_notify`, `CONSUMER_CLASS_MIN_CONFIDENCE[CONSUMER_CLASS_NOTIFICATION]`). The verb is picked only inside the branch that is already named. The anchored branch still says "arrived", and the "Someone" branch is untouched.
- Registry-not-names: the person entity is resolved through `tracked_person_entity_id` (person_ids.py, the one person-id rule). No new parsing of entity-id strings.

## Reject-branch enumeration (`_edge_anchor_gates`)
Each path returns a reason, and `_compute_edge_anchor_ex` counts every reason that comes with a None anchor:
lead_off, direction, provenance, no_slug, no_live_face_legs, face_tier, census_off, no_presence, truncated, partner_blocked, no_own_edge, error. A successful anchor returns "anchored". That is 12 reject paths plus 1 success, every one a string literal, and the set is closed by construction. The reason is passed into `_log_egress_outcome`, which runs on every resolution path, so each D8a row carries it. Tests name every reason (grep count ≥1 each in `test_egress_edge_anchor_reasons.py`). The old `_compute_edge_anchor` wrapper has no callers left in the module, so nothing is counted twice.

## Findings
| SEV | Where | Finding | Bug class |
|---|---|---|---|
| LOW | transit_validator.py `_compute_edge_anchor_ex` docstring | The docstring says the reason is "one of `EDGE_ANCHOR_REASONS`", but that constant does not exist anywhere. The set is closed only by convention. Fix: define a frozenset next to the gate and assert membership in the reasons test. | Doc/code drift |
| LOW | transit_validator.py `_named_entry_verb` "came in" test | This test uses `person.*.last_changed < lo`. After an HA restart, `last_changed` is the boot time, and boot-window edges are excluded. So a resident who crosses within LEAD seconds of boot gets "arrived" instead of "came in". That is today's text and does not regress anything; it is just imprecise right after a restart. | Restart-blind state read |
| INFO | `_named_entry_verb` | It does not apply the partner-confusable block that the anchor path uses. This is acceptable: it only picks the verb, and the name still comes from the resolver at ≥0.75. | n/a |

## Light B
- `edge_anchor_none` is a `field(default_factory=dict)` held in RAM in LayerCounters. Its keys are bounded by the closed reason set, so it cannot grow without limit. It resets at boot, which the sensor attribute says.
- The new D8a payload key `edge_anchor_reason` is additive JSON. The only readers of egress outcomes (camera_census deque) use the outcome string, not this key, so the change is shape-safe.
- Sensor attrs are wrapped in try/except, with defaults `0` / `{}`. No new tasks or listeners.
- `_named_entry_verb` never raises and returns "arrived" when LEAD ≤ 0, when presence is missing, or on any error. The no-op path is byte-identical.

## Tests
`test_egress_edge_anchor_reasons.py`, `test_egress_entry_verb.py`, `test_person_awareness_read_api_ship2.py`: 99 passed.

## Verdict
**SHIP.** No CRITICAL, HIGH or MEDIUM findings. The two LOWs are optional and can go in the same fix-up pass if convenient.

## Fix-up

LOW 1 (closed reason set) fixed e0df18fe0: `EDGE_ANCHOR_REASONS` frozenset in transit_validator.py + `test_reason_set_matches_gate_returns` and a membership assert on every reason test (83 targeted pass). LOW 2 (restart-blind last_changed) not fixed: falls back to today's "arrived" wording, no regression.
