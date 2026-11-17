# Step 7 S1 edge anchor: Review B (async, lifecycle, restart, DB, signal chain)

Commit 6b0401670 on feature/step7-s1-edge-anchor, base ac36af1ba (merge-base verified). Tests (edge_anchor, awareness guard, nightly callsites) run from a clean `git archive` of the commit: 197 passed. The shared worktree had another reviewer's mutation drill applied at the time (transit_validator.py:3136, `persons=None`), so a run from the worktree showed 15 false failures.

## Findings
| Sev | Where | Finding | Class |
|---|---|---|---|
| MEDIUM | __init__.py:7626 | `CONF_EGRESS_CONFUSABLE_PAIRS` is not in `OPTIONS_RELOAD_SUPPRESS_KEYS`, so saving it reloads the Coordinator Manager entry. The value is read fresh on every crossing (transit_validator.py:3016), so the reload does nothing useful. The parent entry is not reloaded (that only happens for EC keys), so there is no watchdog hazard. Sibling Presence-step keys reload too. Fix: add the key to the allowlist and to `_NO_LIVE_ATTR_KEYS`. | needless reload |
| LOW | transit_validator.py:3178 vs 2947/1715 | The trip-wire's `since` is a UTC ISO string, but outcome `started_at` is local ISO from `dt_util.now()`. Comparing them as strings shifts the 7-day window by the UTC offset (about 6 h). | TZ string compare |
| LOW | presence.py:6135-6146 | `get_person_edges_since` swallows its own errors and returns `()`. A failed ledger read therefore counts as "no edge" and does not bump `edge_anchor_error`. The notice still goes out. | silent error |
| LOW (pre-existing) | database.py:2015 | The index is on `(node_id, episode_type, started_at)`, but the query filters by type only, so each nightly run does two full scans. These are reads only, off the write queue. | query cost |

## Holds
- **Edge read:** it is a synchronous scan of an in-memory deque and never awaits. Every exception in `_compute_edge_anchor` is caught and counted, and `_count_layer_event` never raises. The notify is wrapped separately, so INV-NOTICE-ALWAYS holds.
- **+45 s race:** none. Resolution runs at t_E plus `ENTRY_WINDOW` (async_call_later at :1692/:1743). Edges are appended synchronously when the state changes, stamped with that change time (residency.py:110-162).
- **Restart:** `created_ts` makes the ring read as truncated for the first 300 s, and edges inside the boot window are excluded. Counters live in RAM; the trip-wire reads persisted rows and stays quiet until the oldest row in the window carries the `edge_anchor` key.
- **INV-SECURITY:** the bus payload is unchanged. `identity_role`, `nameable`, `face_tier` and `live_face_legs` have no reader outside the producer apart from the amend allowlist (:1006). person_sighting reads only `direction` and `people_count`.

**Verdict: SHIP.** The MEDIUM is recommended but does not block.
