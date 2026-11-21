# Review A + G: feature/unified-room-rules (AI-ROOM-RULES-TRUST-REPAIR-1 D1-D9)

Branch f096b8885 + ba03f7568. Base verified: merge-base 09292d006. The develop commits since the base touch only
docs, kanban and vibememo, with no overlap with the branch's code or tests. HVAC and presence state-of-play docs were
not reopened: the change does not touch HVAC control or presence producers. It consumes `ura_person_location_change`
and keeps the climate block. Targeted tests: 121 passed (compiler, executor, flow, observability, ai_automation,
chaining).

**Verdict: SHIP** (no CRIT or HIGH). Three operator UI decisions are pre-empted in code and must be confirmed or
reverted before deploy (see G).

## Framing A: local correctness

| Sev | Where | Finding / clearance |
|---|---|---|
| LOW | `rule_compiler.py:298-303` | The service is not validated per domain. Any service name in an allowed domain passes, e.g. `media_player.join` or `lock.unlock`. The plan does not widen the domain list, but a misspelled or odd service only fails at run time (`call_failed`). Suggest one allowed-service list per domain. Class: validation gap. |
| LOW | `const.py:5167-5184` | `humidifier`, `water_heater`, `valve` and `vacuum` are in the allowlist but have no data keys. `humidifier.set_humidity` (needs `humidity`) can never compile. This matches the plan; it is a dead branch, not a bug. |
| LOW | `rule_compiler.py:244-246` | The climate entity goes into the prompt's entity list even though every climate action is rejected. This invites the model to produce parse failures. Leave climate out of the prompt list or mark it read-only. |
| LOW | `config_flow.py:15268-15272` | After "change wording" on an automation rule, the automation form comes back without its earlier picks (no defaults from the pending rule). A described rule keeps its text. |
| LOW | `config_flow.py:10496` | The optimizer-step docstring still says zero new CONF keys land in this step, which is now stale. |
| holds | `rule_compiler.py:379-383, 408` | `time_window` crossing midnight is correct. `start == end` is rejected at compile time and treated as false at run time. `datetime.time` objects are always truthy, so 00:00 is safe. |
| holds | `rule_compiler.py:491-513` | The failure kinds stay apart. `model_unavailable` covers a missing or unavailable entity, an unregistered service, a raised call and a timeout (`:534-574`). `parse_failed` covers a bad response. `unsupported` refuses the save. An empty `actions_json` produces "no actions", i.e. `parse_failed`. |
| holds | `rule_compiler.py:96-105, 187-192`; `config_flow.py:15061-15093` | D8: a rule stored only in data is `needs_parse`. On the first write it is copied to options with `needs_parsing` and stays inert until a Re-check clears it. Legacy chains are folded in and `CONF_AUTOMATION_CHAINS` is emptied. |
| holds | `coordinator.py:1049-1066, 1371-1407` | INV-R5: person enter/exit rules match only on the event, through `slug_of` on both sides. The occupancy edge never fires them. On a live check, the person entity slugs equal the display-name slugs (`person.oji_udezue` / "Oji Udezue", and the same for Ezinne, Jaya and Ziri), so the match fires. |
| holds | `coordinator.py:974-988, 1089-1140` | INV-R3: the exempt set skips the gate, and otherwise `manual_mode` is checked before `switch_off`. INV-R6: each matched rule records exactly one decision. A partial block still counts as fired, with the guard listed. |
| holds | `coordinator.py:1626-1778` | INV-R1: the chain path now goes through `_execute_rule_action` (`:936`). The guards are unchanged. `automation` with `skip_condition` is allowed by the allowlist and by the data keys. |
| holds | `coordinator.py:996-1004` | `is_dark(illuminance)` matches its signature (`automation.py:1333`). Missing automation fails closed (`condition_false`). |

## Framing G: goal fidelity

- The charter is delivered. Rules ship on, with no shadow mode. There is one record and one executor. A rule cannot
  be saved without parsed actions. The preview is written by code. Every decision is logged and lands in stats,
  room memory, the digest and the zero-fire trip-wire. The "Run an automation" path works with the model locked, so
  the 12-01 lock does not block the day-1 trust path. No risk reduction changed what is delivered.
- No hard constraint is broken: the allowlist is not widened, the climate block and security cover block are kept,
  and no new DB table is added.
- **Pre-empted operator UI decisions (card: "Operator UI decisions (3)"):**
  1. **When dropdown on Describe a rule: BUILT.** `config_flow.py:15115-15122` adds a required "When" select, so the
     trigger stays out of the model. The plan's §7 mock showed only text and "Only for". The build chose the
     option the card lists. The operator should confirm it.
  2. **Model picker location: BUILT in the Optimizer AI step** (`config_flow.py:10678-10690`,
     `async_step_coordinator_optimization`), not as its own step. This pre-empts the decision. It would also look
     like the OC model setting, which the plan specifically wanted kept separate.
  3. **Confirm step: BUILT as Submit = Save plus a "change wording" checkbox** (`config_flow.py:15287-15298`). A
     plain-language "Save" or "Change the wording" choice (a menu) would follow §7 and the label guide better. A
     checkbox you must tick to *not* save is easy to miss. Pre-empted, and MEDIUM on UX grounds ("smart and simple").

## Must-fix before deploy
None for code correctness. Before deploy: get the operator's ruling on UI decisions 1-3 (the build pre-empted all
three). Item 3 is the one most likely to be reverted.
