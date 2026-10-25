# Review C (test authority, real per-site source mutation): PERSON-BLE-WINS-OVER-STALE-GPS-1

Branch `fix/presence-gps-assistive` @ acab9c3f3 (base f96aaa0ed). Reviewer: framing C.
Method: 62 single-site mutations of production source in a clean worktree, `__pycache__` cleared and
`PYTHONDONTWRITEBYTECODE=1` before each, restored in a `finally`, `git status` clean after.
Target set per mutation: `test_person_gps_assistive.py` + `test_person_gps_assistive_hvac.py` +
`test_v4713_sleep_state_zone_presence_trust.py` (86 pass at baseline). `-x`, drills enabled (`-m ""`).

## Verdict: FIX-REQUIRED (1 MEDIUM, 3 LOW; 6 sites GREEN on neuter)

## Site x RED-on-neuter table (RED rows condensed; first failing test shown)

| Site | Mutation | Result / first failing test |
|---|---|---|
| gate: switch conjunct | drop `ble_leads_on` check | RED `test_switch_off_restores_gps_proof[bermuda]` |
| gate: fleet armed | drop `_fleet_armed` | RED `test_fleet_dead_keeps_home[0]` |
| gate: wifi witness | drop; and allow `home` | RED `test_wifi_home_witness_keeps_home` |
| gate: all-not_home | all->any | RED `test_ble_unavailable_keeps_home_ialpha[unavailable]` |
| gate: seen>=1 | >=0 | RED `test_no_ble_tracker_keeps_home[bermuda]` |
| gate: source_type filter | removed | RED `test_frozen_gps_home_ble_not_home_goes_away` |
| site 1 (Bermuda arm) | overrule disabled / `ble_leads_on` forced True / `.add` dropped | RED (`test_frozen_gps_home_...`, `test_switch_off_restores_gps_proof[bermuda]`) |
| site 2 (twin arm) | same three | RED `test_no_bermuda_branch_twin_site`, `test_switch_off_restores_gps_proof[no_bermuda]` |
| frozenset assign | assign dropped / union-with-previous (never clears) | RED `test_frozen_gps_home_...` / `test_overruled_set_assigned_once_after_loop` |
| fleet floor | ignored | RED `test_fleet_dead_keeps_home[0]` |
| fleet arm window | 360 -> 0 | RED `test_arm_window_boundary[359-home]` |
| dip reset | dropped; latch re-stamped each reading | RED `test_fleet_dead_keeps_home[0]` / `test_frozen_gps_home_...` |
| registry miss | latch not cleared; wrong platform/uid | RED `test_proxy_entity_missing_rule_off` / `test_frozen_gps_home_...` |
| listener | subscribe skipped; callback no-op | RED `test_unsampled_dip_resets_latch_via_listener` |
| tick re-read / ensure call | dropped | RED `test_fleet_dead_keeps_home[0]` |
| listener teardown | on_unload dropped, unsub no-op, ref not nulled, `async_teardown` no-op | RED `test_listener_unsubscribed_on_unload` |
| `__init__` teardown call | dropped | RED `test_unload_entry_tears_down_person_coordinator_listener` |
| 15-min pre-arrival guard | always-arm / never-arm / threshold 0 | RED `test_overrule_arms_pre_arrival_only_after_15_min[900-True]`, `test_frozen_gps_home_...` |
| overrule stamps | reason / confidence dropped | RED `test_frozen_gps_home_...` |
| S3 helper lost_since stamps | dropped | RED (crash KeyError 'Oji Udezue'; a crash-RED, not a behavioural assertion) |
| effective_person_state | no-overruled shortcut, switch check, location==away check, returns home, slug match | RED (`test_switch_off_effective_state_raw`, `test_effective_state_only_differs_when_overruled[home]`) |
| `person_state_for_trust` bypass | skip coordinator | RED `test_zone_persons_home_veto_uses_effective_state[sleep]` |
| `_ble_leads_enabled()` | mgr None->False; presence None->False; ignore field | RED |
| switch class | backing field / unique slug wrong | RED `test_ble_leads_switch_restore_off_fast_and_deferred` |
| 6 reader swaps | aggregation x2, hvac night-trust, hvac main-row, hvac_fans, hvac_zones | all RED (`..._veto_uses_effective_state[sleep/nonsleep]`, `test_hvac_night_trust_effective`, `test_hvac_main_row_home_persons_effective`, `test_hvac_fans_night_hold_effective`, `test_hvac_zone_has_home_person_effective`) |

## GREEN rows (untested sites) = findings

| # | Sev | Site | Neuter | Why it matters | Class |
|---|---|---|---|---|---|
| C1 | MEDIUM | `switch.py:426` `PresenceBleLeadsEnabledSwitch(hass, entry)` in the `async_setup_entry` list | removed from list | Suite stays 86 green. Switch class is tested by direct instantiation only; if registration is lost the kill switch is absent from the UI while the rule stays on. | #62-adjacent / #53 (class built, wire-in unanchored) |
| C2 | LOW | `presence.py:1788` default `_ble_leads_enabled = True` | default -> False | Green: tests use `SimpleNamespace(_ble_leads_enabled=...)` fakes, so the real default-ON is never exercised; a False default silently disables the whole feature on every boot. Upgrade to MEDIUM if the plan treats default-ON as an acceptance criterion (it does: "Default ON"). | wire-in anchor missing |
| C3 | LOW | `person_coordinator.py` `_ensure_proxy_listener` `if eid != self._proxy_entity_id: self._release_proxy_listener()` | release removed | R2-2 claims a changed entity_id re-subscribes; with release gone `_proxy_unsub` stays set and the listener stays on the OLD entity, but nothing tests an entity_id change. | untested claim |
| C4 | LOW | `_apply_s3_away_arm` `no_signal -> away_wifi_only/0.9` rewrite | disabled | The else-arm refactor into the shared helper claims byte-identical behaviour; the `away_wifi_only` rewrite on the NON-overrule arms has no test (overrule path overwrites the reason anyway). Refactor equivalence on the no-op path is unanchored. | byte-identical-on-no-op unanchored |
| C5 | LOW | `effective_person_state` outer `except -> return raw_state`; `person_state_for_trust` `hass.states.get` exception -> None | flipped | Defensive fail-open paths unexercised (E6, E8, `_ble_leads_enabled` exception -> True also GREEN). Low blast radius. | defensive path untested |

C5 is three small rows (E6, E8, E9c).

## Notes
- The O6 mutation went RED only by crashing the tick (KeyError), so lost_since stamping has no direct assertion; counted as covered but weak.
- Mutation harness: `scratchpad/revC_drill.py` (not committed). Tree restored; `git status --short` empty after every run.

## Must-fix before SHIP
1. C1: add a test that drives `switch.async_setup_entry` and asserts a `PresenceBleLeadsEnabledSwitch` is among the added entities.
2. C2: assert a real `PresenceCoordinator`'s `_ble_leads_enabled is True` at construction.
3. C3/C4/C5: LOW, fix in-cycle if cheap (entity_id change re-subscribe test; one `away_wifi_only` regression test on the else-arm; exception-path fail-open tests).
