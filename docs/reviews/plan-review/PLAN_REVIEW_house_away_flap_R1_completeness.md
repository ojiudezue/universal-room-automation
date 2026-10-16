# Plan review R1 (completeness) — PLANNING_house_away_flap_untracked_occupant.md

Reviewer: ura-reviewer, framing COMPLETENESS, 2026-10-16 overnight, read-only.
Read first: PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md, SENSOR_FLEET_CLASSES.md, HVAC state-of-play house-state rows.

**Verdict: FIX-PLAN** (1 HIGH, 2 MEDIUM, 4 LOW).

## Verified claims
- Exactly three automatic AWAY returns in `infer()`: nobody-home `presence.py:1127-1131`, path α `:1169-1181` (no census/zone term, C1 confirmed), path β `:1262-1288`. `:1297` is the AWAY→ARRIVING path, not a producer.
- No other automatic AWAY producer: `HouseStateMachine.transition` is called only at `presence.py:6961`; `force_state` has no callers. The remaining AWAY setters are operator-explicit or boot-time: `set_override` (`select.py:278`, `__init__.py:6195`, `presence.py:8013-8021`), `apply_restored` (`house_state.py:368-431`), and the cold-boot default `initial_state=AWAY` (`house_state.py:153`, `manager.py:225`).
- GUEST-CENSUS D1 clamp: `camera_census.py:6006-6009` (the plan's ~5985-5995 cites the comment block). C4 holds.
- `_schedule_deferred_retry` is at `presence.py:5107-5129`. `FLOOR_WINDOW_S` defaults to 1200 s in the estimator plan. The estimator D6 table has rows for `:1111` and `:1223` only (C6 confirmed).
- Override entity: all three selects exist and are `auto` live: `select.ura_presence_coordinator_house_state_override`, `select.ura_coordinator_manager_house_state_override`, `select.universal_room_automation_house_state_override`.
- EVSE and battery: no SIGNAL subscription. Energy polls `manager.house_state` (`energy.py:8050/8257`).

## Findings
| ID | Sev | Claim | Evidence | Required plan change |
|---|---|---|---|---|
| R1-01 | HIGH | INV-AWAY-DISCHARGE is falsifiable through the reused retry. `_retry_unsub` is one slot shared with the hysteresis retry, so each cancels the other. A blocked transition only re-arms when `trigger != "deferred_retry"`. Any accepted non-AWAY transition also clears the pending retry. Repro: the body-quiet retry fires, AWAY is proposed, and hysteresis blocks it (ARRIVING 60 s / HOME_* 120 s dwell after a recent ARRIVING→HOME). No retry is re-armed, so AWAY waits for the next external event. | `presence.py:7099-7101`, `:6966-6968`, `:5115-5117`; `house_state.py:130-135` | Specify the slot semantics: a separate handle, or re-arm the body-quiet retry when the deferred tick is blocked. State whether periodic census updates are guaranteed when the count is unchanged; if they are not, the timer is load-bearing. Add a test: discharge while hysteresis blocks. |
| R1-02 | MED | The consumer list covers signal subscribers only. Polling AWAY consumers are missing: comfort-fan AWAY veto `fan_veto.py:60`, perimeter vehicle alerts `perimeter_alert.py:2769` / `const.py:2701`, `optimization.py:3661`, `hvac_predict.py:446`, `binary_sensor.py:2315`, `energy.py:8050`. The cost of delaying a real departure by up to W is not priced for security, perimeter or fans. | greps above | Add the rows and price the W-delay per consumer, perimeter and security above all. |
| R1-03 | MED | Restart. The Store saves on machine mutation or the 300 s heartbeat, not on a stamp change, so the restored stamp can be up to 300 s old. A stale or missing stamp → None → the guard passes on the first post-settle tick. A cold boot also starts in AWAY. | `house_state.py:153`; `manager.py:690-694`; PoP §1 heartbeat 300 s | Treat None at boot as last body = boot time (conservative), or persist on each stamp change. Explicitly fence the cold-boot AWAY default (card HOUSE-STATE-SENSOR-BOOT-AWAY-DISPLAY-1). |
| R1-04 | LOW | The boot census seed bypasses `_handle_census_update`, so a seeded count > 0 is never stamped. | `presence.py:2946`, `:2958` | Stamp at the seed, or document why it is not needed. |
| R1-05 | LOW | Both override ids are real; the plan names one of three. | live HA | Name the canonical select and note that the siblings exist. |
| R1-06 | LOW | The claim that "Count memory" has the same semantics as D6 is partial. The estimator shrinks the window to 180 s on an observed outbound crossing. | estimator plan l.60, l.375 | Note that D6 changes the effective delay under the same knob. |
| R1-07 | LOW | The plan's §11 open question: operator overrides, restore and cold boot are not fenced in the plan. | see Verified | Add an explicit fence list (override, restore and cold boot are out of the guard's scope). |

No live DB re-measurement was run.
