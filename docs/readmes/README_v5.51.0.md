# v5.51.0 — Occupied-Fan Guard + Cross-Host Camera Corroboration

## The occupied-fan guard (the architecture answer)
HVAC never dispatches a fan turn-off against a room whose live occupied
sensor reads on — any house state, any room type. Kills the evening
dueling loop (master fan cycled 10x on 8/3) and the non-bedroom sleep
sweeps (living room 23:43). Probe-adjudicated: the exit-evidenced-
vacancy architecture NO-GO'd on sensor coverage (15-39%); the occupied
sensor blocks 7/7 known false sweeps with signals every room has.
Escape valves preserved: zone vacancy sweep, safety stops, operator
global-off all bypass the guard. Inverse risk (stuck-occupied = fan
runs) adjudicated acceptable (pennies + sensor-health NM). Suppressions
write actuation_conflict episodes (suppressed=true — memory now counts
harms PREVENTED); real offs finally write activity rows.

## Slugify fix (M-1 audit — guard was blind in BOTH kids' bedrooms)
memory_facade._slugify now matches HA semantics (punctuation stripped):
"Ziri Bedroom (Bedroom 5)" previously resolved to a nonexistent entity
id, silently failing the guard AND observer open in Ziri's and Jaya's
rooms. Live-room audit table verified; parity + pin tests updated. One
historical episode row keeps the old parenthetical node_id.

## Cross-host camera corroboration OPENED (reviewed flip)
72h stability gate PASSED (0 organic MQTT evictions/flaps/ghosts — all
15 unavailability events map to our deploy restarts + homelab config
work). F1+F2 same-object devices now BOTH contribute person sources;
same-family ON still caps confidence at medium. Open-gate contract
tested; closed-gate collapse pinned via monkeypatch.

## Reviews
2 framing-disjoint (A semantics/inverse-risk: SHIP; B tests/lifecycle:
SHIP w/ M-1 which the audit escalated in-cycle). Builder 3 + reviewer 3
+ orchestrator 4 mutation-reds (incl. slug-semantics revert red).
Suite 19-failure baseline, 8111 passed, zero drift.

## Live Validation — prospective
- **Live (tonight):** zero actuation_conflict episodes with
  suppressed=false; suppressed=true episodes ONLY when a sweep is
  legitimately blocked; family-facing: no fan turns off in an occupied
  room, evening included.
- **Live:** Study A fused sensor sources gain the F2-host sensor
  (cross-host corroboration visible in attributes).
- **Live:** sleep_fan_on_temp_f flipped 0→72 post-deploy; first
  sleep-onset burst tonight (staggered fan_on rows, trigger
  sleep_onset); running/manual-off fans untouched.
- **Live (carried):** v5.49.0 age-gate proof on this restart.
