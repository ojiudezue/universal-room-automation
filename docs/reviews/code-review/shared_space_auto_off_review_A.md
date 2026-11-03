# SHARED-SPACE-AUTO-OFF-FAILSAFE-1 — Review A (local correctness + edge cases)

Branch `feature/shared-space-auto-off-failsafe` @ 01026d5d vs develop 25d52dce (three-dot).
Reviewer framing A only. HVAC/presence state-of-play docs not read: the change only consumes the
tick's `data[STATE_OCCUPIED]` and does not alter any presence producer.

Targeted tests (6 files: failsafe, slice C manual hold, night-light off path, sleep fans/flash,
cycle B config flow, d7 donor hygiene): **172 passed, 41 skipped, 0 failed.**

## Night-key truth table (`automation.py` `_auto_off_night_key`, run directly)

| S | C | local time | key |
|---|---|---|---|
| 23 | 5 | 2027-01-01 02:00 | 2026-12-31 (year boundary OK) |
| 23 | 5 | 2026-12-31 23:00 | 2026-12-31 (same night, no refire) |
| 23 | 5 | 2026-03-01 04:00 | 2026-02-28 (month boundary OK) |
| 23 | 5 | 05:00 | None (cutoff exclusive) |
| 23 | 23 | 23:00 | today (cutoff==start = one hour, old rule) |
| 0 | 5 | 00:00 | today (non-wrap) |
| 1 | 0 | 00:00 | None (wrap, window 01-23) |
| 23.0→23 | 5.0→5 | 2026-11-01 01:00 | 2026-10-31 |

DST: key is hour + `date()` only. Fall-back repeats 01:xx with the same key, so no double fire.
Spring-forward skips 02:xx and the window continues. Holds.

## Findings

| SEV | Where | Finding |
|---|---|---|
| — | `automation.py` `get_auto_off_cutoff_hour` | Float knob holds because `int()` wraps the read, same as the start hour. |
| — | `_shared_space_turn_off_all` (automation.py:4650) | Single caller confirmed. A repo grep finds only `check_scheduled_auto_off` (4528). The leave-on exemption remains at `domain_coordinators/hvac.py:6806` (zone sweep) and the vacancy paths. `light_hold_allowed` is kept. |
| — | fans/switches | Fan Mode Off and the HVAC-owned-elsewhere filters are unchanged. `CONF_HUMIDITY_FANS` is not in the sweep, so a bathroom shower exhaust is not cut by the longer window. |
| — | config_flow.py ~12645, strings/en.json | The cutoff field is added to the options flow (0-23 BOX) with matching strings. The retired warning key stays in the schema with "(retired)" labels, so stored options still load. The config (create) step string was updated too. |
| LOW | `automation.py:~4500` (`_last_auto_off_date`) | Restart inside the window can sweep again once. This is documented, and offs are idempotent on a vacant room. Accepted. |
| LOW | coordinator.py ~5432 `data.get(STATE_OCCUPIED, False)` | A missing key defaults to vacant, which allows a sweep. Every path at coordinator.py 3998-4342 sets the key, so this is not reachable today. |
| MEDIUM (operator awareness, not a code defect) | behaviour, 30 shared-space rooms | The sweep window grows from 1 h to 6 h (23-05), and leave-on lights now go off. Two effects follow for bathrooms and hallways. (a) A leave-on night light goes dark at the first vacant tick after 23:00. This is the plan's stated D2 intent. (b) A motion-only bathroom that briefly reads vacant with a still occupant can now be swept at any time up to 05:00, where before only the 23:xx hour was exposed. Before, the sweep fired regardless of occupancy, so (b) is a narrower trigger over a longer window, not a new class. The operator should confirm (a) for rooms whose leave-on list is meant to act as an all-night light. |
| MEDIUM (test gap, known) | coordinator.py ~5432 wire-in | No test proves the coordinator passes the tick's occupancy. Swapping it for `True`, or dropping the argument (TypeError caught by the surrounding try), stays green. |

### Proposed wire-in test (feasible, small)
Drive the real coordinator periodic block with `coordinator.automation = MagicMock(spec=RoomAutomation)`,
using `AsyncMock` methods. Run one tick with the occupancy producer forced to vacant and one forced to
occupied. Assert `check_scheduled_auto_off.assert_awaited_once_with(False)` and then `(True)`. Then drill
it: mutate the call to `check_scheduled_auto_off(True)` and confirm RED. Do not use a source grep (#62).
If building a full tick is too heavy, extract the call into a one-line coordinator helper that takes `data`
and test that helper. A drill can then target it.

## Verdict: **SHIP**
No CRITICAL or HIGH findings. Recommended before ship: add the wire-in test above, and get an operator
ack on the leave-on night-light effect, MEDIUM (a).
