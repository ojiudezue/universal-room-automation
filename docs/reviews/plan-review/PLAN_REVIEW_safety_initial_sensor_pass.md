# Plan review: PLANNING_safety_initial_sensor_pass.md (SAFETY-NO-INITIAL-SENSOR-PASS-1)

Tier 2-DB plan review, one adversarial pass, 2026-10-16. Citations are against `feature/safety-nm-refire`.

**Verdict: FIX-PLAN (light).** No CRITICAL or HIGH findings. The core design holds: it reuses the single
intent → `evaluate` → `_respond_to_hazard` path, and the ordering claim is correct. Before build, fold the
four MEDIUM findings into the plan.

## Verified (holds)
- **Setup paths.** `async_start` is called once (`__init__.py:4659`). It sets up the coordinators (`manager.py:497-502`) and then NM (`:505-514`). The only other `coordinator.async_setup()` caller is re-enable (`manager.py:1273`). Every `register_coordinator` call runs before `async_start`. A URA/CM reload re-runs `async_setup_entry` → `async_start`. **The plan enumerates every path.**
- **`queue_intent` drops intents when `not self._running`** (`manager.py:933`). `_running` is set at the top of `async_start`, so pass intents are accepted. Intents queued while a batch is in flight are rescheduled in `finally` (`:1011-1019`).
- **Late recovery (unavailable/unknown → on).** The handler queues an intent (`safety.py:1603-1633`). The second raise takes `not is_new` (`:2487-2499`), so there is no double page. A sensor that first appears (old_state None → on) also queues an intent.
- **`evaluate` uses `intent.data["state"]`** (`safety.py:1697`), so the pass's snapshot is what gets classified.
- **Numeric CO has no sustain hold.** Only TVOC (`:2010+`) and the CO2 log-only rung (`:1990-2009`) have one, so a single seeded CO sample raises immediately.
- **Every hazard writer is listed (W1-W5).** The pass adds no new writer.

## Findings
| ID | Sev | Claim | Evidence | Required plan change |
|---|---|---|---|---|
| P-01 | MED | The D3 gate is left "not verified", but it can be resolved now. `acknowledge_notification` acks only the single latest unacked CRITICAL row. | `database.py:4628-4651` (`ORDER BY timestamp DESC LIMIT 1`) | Record this as verified: ack does NOT cover the duplicate, so D3 code is required. Delete the "collapse to test only" branch. |
| P-02 | MED | PICK 1 misses an option that strictly dominates (a) and (b). Extend the D3 accessor to cover a **recovered unexpired COOLDOWN** on the same key. The seed then suppresses its page, while `is_hazard_active` is True, so `_cooldown_expired` → `_re_evaluate_hazard` re-fires at expiry. Expired cooldown: no NM state, so the seed pages. Result: no early re-page and no permanent silence. | NM COOLDOWN recovery `notification_manager.py:4990-5014`; F8 drop `:965-971`; the "early re-page" cost in plan §5 Q3 | Add PICK 1 (c), "honor a recovered cooldown, page otherwise", and recommend it. Add the test `test_initial_pass_honors_recovered_cooldown`. |
| P-03 | MED | §9 calls the pre-NM-setup ordering hazard "not verified as reachable". It is reachable. Safety subscribes in its own `async_setup` and later coordinators' setups await for seconds (HVAC waits on Presence). The batch window is short, so a Shelly flood event at 16-23 s (§4) can run `_execute_action` → `async_notify` before `NM.async_setup` and its DB recovery. A seeded/event hazard can then write a row that recovery later shadows. | `manager.py:497-514`, `:933-945`; plan §4 timings | Restate it as reachable (pre-existing) and mint a card. The pass itself is unaffected: a hazard already raised makes the seed `not is_new`. |
| P-04 | MED | PICK 2 (a) says egress unlock is safe because the toggle is OFF. Once the toggle is ON, a stuck-ON smoke/CO detector unlocks egress on **every** reload/restart, including while the house is AWAY. On the live path that happens once per episode. Reload storms have historically run ~5×/night. | `security.py:2041-2090`; memory `project_reload_storm_refuted_restart_storm_live` | Keep (a), but name this risk explicitly in PICK 2 and add a code trip-wire: an NM/anomaly alert when the pass seeds a CRITICAL hazard from a sensor whose `last_changed` predates boot by more than N h (stuck-detector signal). Alternatively, card it as a follow-up. |
| P-05 | LOW | INV-SEED(a): "first intent batch after the pass". If a batch is in flight, the pass intents land in the following batch. | `manager.py:953`, `:1011-1019` | Reword to "by the end of the first batch that drains the pass intents". |
| P-06 | LOW | The live criterion `seeded=0` cannot tell "pass works" from "pass classifies nothing". The only discriminator is the log line's presence. | plan §7 D1 Live | Add a `checked=N` count to the log line and require N = the size of the discovered binary+CO fleet that is not unavailable. |
| P-07 | LOW | D3 suppression has no discharge statement for the case where NM later leaves REPEATING without an ack (e.g. NM disabled mid-episode). | `feedback_suppression_needs_discharge` | One line: the discharge is NM's REPEATING loop; if NM exits that state, the next state-change or refire re-pages. |

The knob ladder (two rung-1 consts, kill-switch semantics documented) is OK. Non-goals are explicit. The Q2 unavailable rule is sound. The CO threshold at boot is sound.
