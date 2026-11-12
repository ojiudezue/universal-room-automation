# DRAFT — Lock regime: hold suspicious arrivals (stale-source home edges)

Card: GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 residual. Plan: `docs/planning/PLANNING_lock_suspicious_arrival_hold.md` rev 2 (plan review applied, §12). Branch `feature/lock-suspicious-arrival-hold`. Version not assigned (draft; rename on deploy).

## Why

In 7 days (11-05..11-12) Oji's person entity read `not_home -> home` 78 times for under 1.2 s. Each time the phone tracker went `unavailable`, HA's person fell back to a second GPS device (the iPad) whose `home` was hours old, then the phone came back. 49 of those blips also jumped the proximity distance to 0 ft. With the garage lockout or the away lock on, every blip would have unlocked. The 11-11 tracker trim (one GPS device per person) stops the mechanism in this house today; this change is the guard for the day a second GPS device is added, and for other installs.

## What changed

- **One rule** (`arrival_edges.stale_source_arrival`): an arrival is suspicious when the person's `source` tracker did not itself change at the edge (`person.last_changed - source.last_changed > 10 s`, or no source). Real arrivals measured at most 0.0003 s; blips at least 4,119 s. 0 of 40 real arrivals would be held.
- **Hold, then decide** (`security_lock_regime.py`). A suspicious person edge waits `number.ura_garage_lockout_arrival_hold` seconds (default 5, 0 = off). If the person reverts inside the hold, the edge and its revert cancel with no state change. If the person still reads the held state at the end, the original edge is replayed through the normal path (time stamps carry the edge's own time). Attribute-only updates during the hold change nothing.
- **Same hold on every unlock path that a blip feeds:** the person edge (garage release, approach zone, away lock, face-corroboration stamp), the `SIGNAL_PERSON_ARRIVING` path (geofence / ble / camera_face and the held-face re-check), and the proximity crossing (re-read at the end of the hold).
- **Never held:** edges whose source changed at the edge (every real arrival), edges in the first 600 s after the lock regime starts (boot), and a proximity crossing while the person is `not_home` (a real approach).
- **Away lock:** if its 300 s all-away dwell comes due during a hold, it waits for the hold to end (plus 0.1 s) instead of spending its one attempt.
- **New knob:** `number.ura_garage_lockout_arrival_hold` on the Security Coordinator device, 0-60 s, default 5, 0 = previous behaviour exactly. Applies to the garage lockout and the away lock. In both reload-suppress lists, so changing it never reloads the CM.
- **Diagnostics:** lock-regime snapshot attributes `lock_regime_arrival_holds`, `lock_regime_arrival_signal_held`, `lock_regime_arrival_hold_confirms`, `lock_regime_held_edges`.

Not changed: house-state releases, the boot recheck, the 15-minute blip rule, face-corroboration rules, other consumers of the same blips (expected-arrival sanction, HVAC pre-arrival, music following; follow-up card per plan §7).

## Residuals (plan §9)

- A stale-source `home` that lasts longer than the hold releases at the end of the hold (develop behaviour, H seconds later).
- Holds are not persisted; a restart or lock-regime reload during a hold drops it.
- A proximity sensor that does not resolve to a person bypasses the proximity gate (develop behaviour).
- A dropped arriving signal is not replayed if the hold is cancelled; the next real edge carries the arrival.

## Tests

- `test_arrival_edges.py` (6): the predicate, incl. `last_changed` vs `last_updated`.
- `test_lock_arrival_hold.py` (24): blip pair no-op (garage and away stamp), fresh source releases in the same callback, confirm at H with the edge timestamp, cancel by another value, teardown, approach zone, attribute-only event keeps the hold, away dwell deferral, boot window exempt, config re-read at confirm, synthetic proximity hold on an already-home person, P2 gate (incl. signal before the state listener, face not corroborated by a blip, held-face re-check), P5 gate, knob round trip / live read / suppress lists, snapshot counters.
- `test_lock_arrival_hold_real_ha.py` (3): real HA core and real `person` component: 2-GPS dropout held and dropped, attribute-only refresh stays held, BLE-only arrival instant.
- `test_lock_arrival_hold_replay.py` (3): the committed probe fixture (118 edges, 52 crossings; `scripts/probes/lock_arrival_edge_probe.py`) replayed through the real regime: 40/40 real edges and 3/3 real crossings release in their own callback, 78/78 blips and 49/49 blip crossings never unlock, final state equals the blips-removed run; H = 0 equals the develop golden (`fixtures/lock_arrival_hold_develop_golden.json`, generated from develop b7e4289e).
- 17 per-site mutation drills (the plan's 12 plus 5 call-neuter drills), each RED on its named test.

## Live validation (to fill after deploy)

Prospective:
- `number.ura_garage_lockout_arrival_hold` exists on the Security Coordinator device and reads 5.
- Lock-regime snapshot attributes show `lock_regime_arrival_holds` 0 and `lock_regime_held_edges` [] after a resident's real arrival outside the first 10 minutes after a restart. A non-zero count with no second GPS device on any person = a false hold (a real-arrival delay); check `person.*.source` at that edge.
- Organic, once the lockout is on: each resident arrival's lockout release time equals the person edge time (within 1 s) in the activity log.
