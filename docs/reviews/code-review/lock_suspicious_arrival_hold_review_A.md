# Review A — lock suspicious-arrival hold (local correctness + "never delay a real unlock")

Branch `feature/lock-suspicious-arrival-hold` (70c6d4ac, 1eec0050). Merge-base with origin/develop verified = b7e4289e.
I read PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md first. Tests: the 9 arrival-hold / arrival-edges / lock-regime / garage-lockout / away-lock files ran together, 377 passed.

## Live ground truth (ha_eval_template, 2026-11-12)
For every person with a source, `person.last_changed - source.last_changed` is negative (-30 s to -4363 s): the source tracker changes after the person does, and the person stays where it is. So steady-state persons do not read stale. `person.wall_kiosk` has no source, and it reads `unknown`, so `_NOT_ARRIVED` returns False. That backs the "HA person always carries source when arrived" assumption.

## Findings

| # | Sev | Where | Finding |
|---|---|---|---|
| A1 | LOW | arrival_edges.py:48 / security_lock_regime.py:1036 | A REAL arrival can be held ≤H when it looks stale. With two GPS trackers (HA picks the GPS tracker with the latest `last_updated`), the phone may have read `home` since T0 while another tracker reporting not_home updated later. An attribute-only refresh of the phone then flips the person to `home`, with source.last_changed=T0 → held for 5 s, then confirmed. The worst case is a 5 s delay. The edge is never dropped unless it reverts within H, and the next fresh edge releases. This can't be told apart from the blip, so it is accepted by design. |
| A2 | LOW | security_lock_regime.py:1036-1041 (D3) | The D3 stale test also covers named zones. If a person in a zone reads stale (e.g. the source switched to an older tracker while the state stayed the same), geofence/ble/face P2 signals are DROPPED, not queued. The unlock then waits for the person edge to `home`, which is fresh and not held. This is a delay, not a loss. The live probe shows no person currently in this state. If it shows up, the remedy is to limit the D3 stale test to `home`. Not a must-fix. |
| A3 | LOW | security_lock_regime.py:1540-1552 (D4 synthetic) | The synthetic hold takes edge_ts from the person's own last_changed. For a person whose state is old, due is already in the past, so `call_later(0)` confirms almost immediately and proximity releases after about one loop tick. The real-approach case (person not_home) is never stale, so it releases at once. Holds because of max(0, due-now). |
| A4 | LOW (deviation #7) | security_lock_regime.py:2549 `_record` | arrival_hold, confirmed and cancelled records overwrite the garage `last_action`, so a cancelled blip hides the last real engage/release in the snapshot. Grep shows no decision consumer of `last_action` (display only). Acceptable. Optional: give these records their own `last_hold_action` key. |
| A5 | clear (deviation #1) | quality/tests/_lockout_harness.py:212 | The harness auto-injects a fresh `source`. Production hides nothing here. A real HA person that reads home/zone always has a source (live probe above). Missing source → `True` → hold, which can only DELAY by H: confirm re-reads state and replays, and nothing is dropped. Explicit stale-source tests pass their own `source`, and test_arrival_edges covers the missing-source and missing-state branches directly. |
| A6 | clear | arrival_edges.py:48-82 | M is a strict `>`, set at 10 s against a measured gap (real ≤0.0003 s, blips ≥4119 s). The function uses `last_changed`, never `last_updated`. The event's new_state is used (F2). not_home/unknown/unavailable → False. |
| A7 | clear | security_lock_regime.py:1151-1182 | Hold, same-state keep, revert-cancel and other-value logic. A same-value fresh event during a hold keeps the hold (≤H delay, then confirm). A revert cancels with no `_away_on_person` reset. Other values collapse to the held old_val. An `old is None` event drops the hold. |
| A8 | clear | security_lock_regime.py:1300-1332 | Confirm pops before the replay, re-checks torn_down and live state, re-reads cfg, and replays with edge_ts so stamps carry the original time (INV-H5). Proximity sids are re-read against the radius and released for a resident. |
| A9 | clear | `_should_hold` | The boot arrival window is exempt. H≤0 → develop path, byte-identical: every new branch is gated on `_hold_s>0` or on a non-empty `_held_edges`. Teardown unsubs every hold. |
| A10 | clear | security_lock_regime.py:2235-2250 | Away-dwell deferral: the dwell defers to max(due)+0.1 s only for listed persons, re-arms `_away_pending_at`, and does not use up `_set_attempted`. The timer handle is replaced after it fires (the old one is spent). |
| A11 | clear | number.py:4481, const.py:3755-3763, __init__.py:7398/7706, strings/en.json | Knob: 0..60 s step 1, default 5, 0 = off. It is in both suppress lists, and strings.json and en.json are identical. |

## Truth table — stale_source_arrival(M=10)
| person state | source attr | source state | p.lc − s.lc | result |
|---|---|---|---|---|
| not_home/unknown/unavailable/None | any | any | any | False |
| home/zone | missing | – | – | True (hold ≤H) |
| home/zone | set | missing | – | True |
| home/zone | set | present, lc missing | – | True |
| home/zone | set | present | ≤10 s (incl. negative) | False |
| home/zone | set | present | >10 s | True |

## "Never delay a real unlock"
I found no path that DROPS a real unlock. On the edge paths the worst delay is H (5 s), and only when the edge reads stale (A1, which can't be told apart from a blip). Under A2, early P2 signals give way to the later fresh person edge. A real approach (not_home → fresh home) is never held.

## Verdict: SHIP
No CRITICAL, HIGH or MEDIUM findings. A1-A4 are LOW and optional.
