# Review D: reserve write governor (EC-RESERVE-WRITE-GOVERNOR-1), adversarial completeness

Branch `feature/reserve-governor`, range 53b3ecb8f..1c5d9bc97. Framing D: diff-blind, the whole reserve surface including pre-existing code.

## Findings

| # | SEV | Inv | Where | Finding / repro | Bug class |
|---|---|---|---|---|---|
| D-1 | MEDIUM | G1 | `quality/tests/test_reserve_write_chokepoint_lint.py:61-74` (`_call_qualifies`) | The mixed form `hass.services.async_call("number", service="set_value", service_data={...})` is not matched. Positional takes only `args[:2]` (length 1 here), and the keyword branch needs both `domain=` and `service=`. This is a legal HA call with all-literal arguments, so it is not one of the documented known limits (variable/constant/runtime-built). Verified: `scan_source(<that line>)` returns `[]`. Fix: qualify when the domain comes from `args[0]` OR `domain=`, and the service from `args[1]` OR `service=`. Add a negative-control test. | #53 one-missed-site (lint hole) |
| D-2 | MEDIUM | G2 (pre-existing) | `optimization.py:4606` and `:4749` (`_dispatch_device_action` / `_dispatch_config_action`), domain gate `const.py OPTIMIZER_ALLOWED_DOMAINS_CONFIG={"number","select"}` | The Optimizer is a live variable-domain `number.set_value` writer that can target the battery reserve. Nothing excludes the reserve entity: the only guard is the operator-seeded `CONF_OPTIMIZER_SAFETY_DENY_ENTITIES`, empty by default, and a ±20% clamp. Repro: optimizer level `propose_config`, a Tier-2 LLM finding `{service:"number.set_value", target:<reserve write-leg>, value:24}` while the reserve is 20. It dispatches 24 to hardware with **no reserve_write row**; only an optimizer `actuated` row is written. The plan's "no example in the repo shows today" for variable-domain writers is false. Minimum fix: add it to the plan's known limits and card a reserve-entity hard deny in the optimizer, or have the optimizer call `_record_reserve_dispatch`. Not a ship blocker for the governor itself. | #53 / undocumented writer |
| D-3 | LOW | G1 | lint design (count-pinning per `(module,function)`) | `kind` is never verified. Retargeting one of the 2 writes in `_execute_shed_action` or `energy_pool.determine_actions` (both `non_reserve`) at the reserve entity keeps the count and passes the lint. Inherent to the approach; document it under known limits. | #62-adjacent (anchor ≠ semantics) |
| D-4 | LOW | G2 | `energy.py` `_record_reserve_dispatch` memo update (written rows, including FAILED) | A FAILED row sets the memo. The next APPLIED re-send at the same `(path,value,owner)`, with hardware already holding that value, is then gated, so the ledger's last word stays "failed" even though the write recovered. Repro: EVSE hold active, hold 60, HW 60, no strategy reserve action, so the overlay appends `set_value(60)` every tick (`energy.py:5519-5523`). At tick T the cloud raises: FAILED row. At T+5 min the call succeeds with pre_state 60: no row. Fix: don't update the memo on FAILED, or put `status` in the key. | Coincidental equality (#63-adjacent) |

## Cleared (holds because …)

- **Timer path (C1):** every decision action goes through `energy.py:7440-7451`, and the tap's value is `action_spec["data"]["value"]`, which is the same dict `_execute_service_action` sends (`:7801-7809`). The overlay's update-in-place and append legs, blind de-escalation (`energy_battery.py:5664`, returned in `decision["actions"]`) and DP fold all flow through it. All reserve emitters resolve the write leg (`energy.py:5340`, `energy_battery.py:5650`, `:6355`), so `target == reserve_eid` holds.
- **Other timer dispatch loops** (`energy.py:6650-6980`, `7416`, `7488-7540`, load-shed `9033`) carry EV, plug, pool or shed actions only. The shed `number.set_value` targets `self._pool._speed_entity` (`:8764`, `:8788`).
- **Evaluate path (C2):** `_evaluate_battery` has a single caller, `evaluate()` (`energy.py:1384`). Nothing after it can raise and drop actions. Only energy emits reserve actions, and at most one per decision, so `ConflictResolver` (`manager.py:97-150`) cannot drop a DEFERRED action. CM execution failure is a documented limit. In observation mode the timer is gated (`:6591`) but evaluate is not (pre-existing, carded). The DEFERRED row is truthful because the CM really dispatches.
- **force_redispatch (C3):** both rows carry `live_desire`, exactly what `async_call` sent (`energy_battery.py:6817-6820`). Each row is in its own guard after the failure record or ledger stamp.
- **Self-heal / write-verify:** the only actuation is via `force_redispatch` (`energy_write_verify.py:2344`). No boot or restore reserve write exists outside `determine_mode`.
- **Other packages:** `radar_tuning.py:274` and `energy_pool.py:4963` are non-reserve. button/switch/config_flow `async_call`s are notify, persistent_notification or radar.
- **G3:** the new reads (`_get_entity`, `_get_state_float`, `_resolve_hold_owner`, `reserve_soc`) are pure. The only side effect is a one-time INFO in `_cloud_write_target`. The helper is sync with no await, so it adds no yield before `_note_battery_dispatch_outcome`. The C2 call sits before `actions.append`, but the helper's outer `except Exception` makes it non-raising and its arguments are dict `.get`s. Golden fixture commit f99ce6714 predates the governor commit 0c4e007b0.

## Invariant checklist

| Inv | Verdict |
|---|---|
| INV-G1 (statically visible writers allowlisted) | **LEAK**: D-1 mixed positional/keyword form; D-3 kind not checked (design) |
| INV-G2 (one truthful row per real dispatch) | **LEAK (pre-existing, out of diff)**: D-2 optimizer writer. Within URA's energy paths it holds, apart from the D-4 gate nuance |
| INV-G3 (no behaviour change) | PASS |

## Test note
Cycle files: lint + A/B are green. `test_reserve_write_rows.py` showed 6 failures while Reviewer C's mutation drill had `energy.py` modified in this shared worktree (`git status`: ` M energy.py`, `drill_c_tmp.py`), so that run was contaminated. Re-run once C restores.

## Verdict
**FIX-REQUIRED (small):** D-1 (lint matcher + negative control). D-2: at minimum add it to the plan's known limits and card it (`EC-OPTIMIZER-RESERVE-DENY`). D-4 is an optional LOW fix in-cycle.
