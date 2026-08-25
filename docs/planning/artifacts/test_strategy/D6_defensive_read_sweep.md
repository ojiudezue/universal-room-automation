# D6 — Defensive-read-of-polluted-state sweep

Seed: `test_reboot_pickup_d2.py:151` read `_dc.__path__[0]` off a module another test had stubbed with an
empty `__path__`, raising `IndexError` at import/collection time. The generalisation: *defensive code that
reads polluted state is not defensive.* This sweep enumerates the siblings.

## Counts

| quantity | count |
|---|---|
| `<mod>.__path__[idx]` READ sites | 85 in 67 files |
| `__path__ = []` EMPTIER sites | 95 in 49 files |
| of those, emptying a PROCESS-GLOBAL `homeassistant*` name | 18 |
| **SAFE** reads (repaired unconditionally, or `getattr(...,None)`-truthiness guarded) | **52** |
| **AT-RISK** reads (repair conditioned on PRESENCE, not CONTENT) | **33** in 15 files |

## The seed site is confirmed FIXED

`quality/tests/test_reboot_pickup_d2.py:135` now reads:

```python
def _ensure_path(mod, path):
    """Give `mod` a usable __path__ without clobbering a good one."""
    if not getattr(mod, "__path__", None):
        mod.__path__ = [path]
```

`getattr(mod, "__path__", None)` is falsy for BOTH a missing attribute and an empty list, so the stub gets
repaired either way. It appears in the SAFE bucket, not AT-RISK — the plan's acceptance criterion holds.

## The at-risk idiom, precisely

There are two spellings of the same mistake, and they differ from the fix by one word:

```python
# AT-RISK — presence-based. An emptied stub passes both of these.
if cc is None or not hasattr(cc, "__path__"):   # _energy_bootstrap.py:172
    ...repair...
ura_path = os.path.join(cc.__path__[0], ...)    # _energy_bootstrap.py:181  -> IndexError

if _cc is None:                                 # test_attainability_branch.py:92
    ...repair...
_ura_path = os.path.join(_cc.__path__[0], ...)  # test_attainability_branch.py:101 -> IndexError

# SAFE — content-based. Only this repairs an emptied stub.
if not getattr(mod, "__path__", None):
    mod.__path__ = [path]
```

## Blast radius

Every AT-RISK read is at **module top level**, so it fires during **collection**, not during a test.
Observed consequence, measured: selecting the 47-file 'emptier cohort' plus one victim produces
`10 errors` / `11 errors` and **zero tests run** — the affected files never collect.

On the specific claim that this *aborts the entire suite*: pytest reports a module-level exception as a
per-file collection ERROR and continues, and the eight captured full-suite runs all completed (9,403+
tests, 17 errors, all 17 from one file). **This sweep cannot distinguish** "the seed incident aborted the
whole run" from "the seed incident errored one file and the abort had another cause" — the run that
produced the seed observation was not captured. What IS measured: 33 sites can turn a sibling's stub into
a collection error, and collection errors take the whole FILE, not one test.

## AT-RISK sites

| file:line | var | why at risk | source |
|---|---|---|---|
| `quality/tests/_energy_bootstrap.py:181` | `cc` | repaired only when `not hasattr(x,'__path__')` — an emptied stub passes hasattr, repair is skipped, `[0]` raises IndexError | `ura_path = os.path.join(cc.__path__[0], "universal_room_automation")` |
| `quality/tests/perimeter/test_circling_founding_case.py:99` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/perimeter/test_circling_severity_per_state.py:34` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/test_arbitrage_completed_chunk_hold_precedence.py:113` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/test_arbitrage_completed_chunk_hold_precedence.py:118` | `_ura` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = _ura.__path__[0]` |
| `quality/tests/test_arbitrage_completed_chunk_hold_precedence.py:138` | `_dc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_dc_path = _dc.__path__[0]` |
| `quality/tests/test_arbitrage_solar_attainability_ladder.py:127` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/test_arbitrage_solar_attainability_ladder.py:132` | `_ura` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = _ura.__path__[0]` |
| `quality/tests/test_arbitrage_solar_attainability_ladder.py:152` | `_dc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_dc_path = _dc.__path__[0]` |
| `quality/tests/test_attainability_branch.py:101` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/test_attainability_branch.py:106` | `_ura` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = _ura.__path__[0]` |
| `quality/tests/test_attainability_branch.py:127` | `_dc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_dc_path = _dc.__path__[0]` |
| `quality/tests/test_dp_yields_to_excess_solar.py:115` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/test_dp_yields_to_excess_solar.py:120` | `_ura` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = _ura.__path__[0]` |
| `quality/tests/test_dp_yields_to_excess_solar.py:140` | `_dc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_dc_path = _dc.__path__[0]` |
| `quality/tests/test_energy_load_shedding_correctness.py:120` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/test_energy_load_shedding_correctness.py:125` | `_ura` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = _ura.__path__[0]` |
| `quality/tests/test_energy_load_shedding_correctness.py:145` | `_dc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_dc_path = _dc.__path__[0]` |
| `quality/tests/test_envoy_boot_decoupling.py:128` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/test_evse_drain_precedence_session_b2b_i.py:127` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/test_evse_drain_precedence_session_b2b_i.py:132` | `_ura` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = _ura.__path__[0]` |
| `quality/tests/test_evse_drain_precedence_session_b2b_i.py:152` | `_dc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_dc_path = _dc.__path__[0]` |
| `quality/tests/test_evse_drain_precedence_session_b2b_ii.py:141` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/test_evse_drain_precedence_session_b2b_ii.py:146` | `_ura` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = _ura.__path__[0]` |
| `quality/tests/test_evse_drain_precedence_session_b2b_ii.py:166` | `_dc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_dc_path = _dc.__path__[0]` |
| `quality/tests/test_evse_drain_precedence_session_b2b_iii.py:128` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/test_evse_drain_precedence_session_b2b_iii.py:133` | `_ura` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = _ura.__path__[0]` |
| `quality/tests/test_evse_drain_precedence_session_b2b_iii.py:153` | `_dc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_dc_path = _dc.__path__[0]` |
| `quality/tests/test_evse_drain_precedence_session_b2c1_fixup.py:126` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/test_evse_drain_precedence_session_b2c1_fixup.py:131` | `_ura` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = _ura.__path__[0]` |
| `quality/tests/test_evse_drain_precedence_session_b2c1_fixup.py:151` | `_dc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_dc_path = _dc.__path__[0]` |
| `quality/tests/test_exterior_track_linker.py:75` | `_cc` | repaired only when `x is None` — a present-but-emptied stub is trusted, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |
| `quality/tests/test_routine_forecaster.py:144` | `_cc` | repaired only when `not hasattr(x,'__path__')` — an emptied stub passes hasattr, repair is skipped, `[0]` raises IndexError | `_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")` |

### Mechanical fix (one line per site)

Replace the presence test with the content test:

```python
-if _cc is None or not hasattr(_cc, "__path__"):
+if _cc is None or not getattr(_cc, "__path__", None):
```

and for the bare-read sites, route through the `_ensure_path` helper already written in
`test_reboot_pickup_d2.py:134-136`. The plan's discriminator was `at-risk ≥ 3 ⇒ follow-up sweep card`.
Measured **33**.

## EMPTIER sites that write to process-global names

These are the files whose mere COLLECTION mutates state every later file reads. `sys.modules` is
process-wide; there is no per-file isolation.

| file:line | source |
|---|---|
| `quality/tests/test_fan_recheck_deferred_surfaces.py:48` | `sys.modules["homeassistant"].__path__ = []` |
| `quality/tests/test_fan_recheck_mode2_cycle.py:56` | `sys.modules["homeassistant"].__path__ = []` |
| `quality/tests/test_freeze_floor.py:75` | `_stub_module("homeassistant").__path__ = []` |
| `quality/tests/test_freeze_floor.py:83` | `_stub_module("homeassistant.helpers").__path__ = []` |
| `quality/tests/test_freeze_floor.py:106` | `_stub_module("homeassistant.util").__path__ = []` |
| `quality/tests/test_freeze_floor.py:565` | `_stub_module("homeassistant.components").__path__ = []` |
| `quality/tests/test_heatcool_enforcer.py:60` | `_stub_module("homeassistant").__path__ = []` |
| `quality/tests/test_heatcool_enforcer.py:68` | `_stub_module("homeassistant.helpers").__path__ = []` |
| `quality/tests/test_heatcool_enforcer.py:91` | `_stub_module("homeassistant.util").__path__ = []` |
| `quality/tests/test_hvac_offphase_integration.py:64` | `_stub_module("homeassistant").__path__ = []` |
| `quality/tests/test_hvac_offphase_integration.py:72` | `_stub_module("homeassistant.helpers").__path__ = []` |
| `quality/tests/test_hvac_offphase_integration.py:95` | `_stub_module("homeassistant.util").__path__ = []` |
| `quality/tests/test_v4513_1_zone_dedup.py:76` | `sys.modules["homeassistant"].__path__ = []` |
| `quality/tests/test_v4513_gap_fixes.py:205` | `sys.modules["homeassistant"].__path__ = []` |
| `quality/tests/test_v4514_anomaly_visibility.py:65` | `sys.modules["homeassistant"].__path__ = []` |
| `quality/tests/test_v4519_transition_detector_teardown.py:235` | `sys.modules["homeassistant"].__path__ = []` |
| `quality/tests/test_v4519_transition_detector_teardown.py:248` | `sys.modules["homeassistant.util"].__path__ = []` |
| `quality/tests/test_v478_egress_window.py:63` | `sys.modules["homeassistant"].__path__ = []` |

## SAFE sites (for completeness)

| file:line | var | why safe |
|---|---|---|
| `quality/tests/_provenance_harness.py:112` | `_cc` | unconditional repair at module top |
| `quality/tests/test_battery_inclement_arbitrage_floor.py:92` | `_cc` | unconditional repair at module top |
| `quality/tests/test_battery_inclement_precedence.py:77` | `_cc` | unconditional repair at module top |
| `quality/tests/test_bayesian_b2_prediction_sensors.py:149` | `_cc` | unconditional repair at module top |
| `quality/tests/test_bayesian_predictor.py:99` | `_cc` | unconditional repair at module top |
| `quality/tests/test_coordinator_diagnostics.py:106` | `_cc` | unconditional repair at module top |
| `quality/tests/test_data_pipeline.py:88` | `_cc` | unconditional repair at module top |
| `quality/tests/test_database_resilience.py:88` | `_cc` | unconditional repair at module top |
| `quality/tests/test_day_boundary_tou.py:89` | `_cc` | unconditional repair at module top |
| `quality/tests/test_db_incremental_vacuum.py:90` | `_cc` | unconditional repair at module top |
| `quality/tests/test_db_write_ready_lossless_timeout.py:101` | `_cc` | unconditional repair at module top |
| `quality/tests/test_db_write_worker_boot_race.py:107` | `_cc` | unconditional repair at module top |
| `quality/tests/test_domain_coordinators.py:118` | `_cc` | unconditional repair at module top |
| `quality/tests/test_energy_battery.py:88` | `_cc` | unconditional repair at module top |
| `quality/tests/test_energy_consumption.py:94` | `_cc` | unconditional repair at module top |
| `quality/tests/test_energy_evse.py:85` | `_cc` | unconditional repair at module top |
| `quality/tests/test_energy_pool_drain.py:77` | `_cc` | unconditional repair at module top |
| `quality/tests/test_energy_pool_fill_priority.py:72` | `_cc` | unconditional repair at module top |
| `quality/tests/test_energy_restart_resilience.py:92` | `_cc` | unconditional repair at module top |
| `quality/tests/test_energy_tou.py:76` | `_cc` | unconditional repair at module top |
| `quality/tests/test_energy_write_verification.py:106` | `_cc` | unconditional repair at module top |
| `quality/tests/test_envoy_auto_derive.py:91` | `_cc` | unconditional repair at module top |
| `quality/tests/test_ev_grid_cap.py:46` | `_cc` | unconditional repair at module top |
| `quality/tests/test_ev_offpeak_proactive.py:211` | `_cc` | unconditional repair at module top |
| `quality/tests/test_evse_offpeak_fill_release.py:84` | `_cc` | unconditional repair at module top |
| `quality/tests/test_evse_solar_aware_ux.py:80` | `_cc` | unconditional repair at module top |
| `quality/tests/test_fan_layer_2_uniqueness_gate.py:56` | `_cc` | unconditional repair at module top |
| `quality/tests/test_fill_priority_daylight_restoration.py:83` | `_cc` | unconditional repair at module top |
| `quality/tests/test_hc_precool_oc_observability.py:132` | `_cc` | unconditional repair at module top |
| `quality/tests/test_hvac_fan_control.py:92` | `_cc` | unconditional repair at module top |
| `quality/tests/test_inclement_alert_classifier.py:57` | `_cc` | unconditional repair at module top |
| `quality/tests/test_inclement_solar_horizon.py:43` | `_cc` | unconditional repair at module top |
| `quality/tests/test_metric_baseline_integration.py:87` | `_cc` | unconditional repair at module top |
| `quality/tests/test_music_following_coordinator.py:108` | `_cc` | unconditional repair at module top |
| `quality/tests/test_notification_manager.py:134` | `_cc` | unconditional repair at module top |
| `quality/tests/test_perimeter_alert_nm_routing.py:91` | `_cc` | unconditional repair at module top |
| `quality/tests/test_predicted_energy_tomorrow.py:27` | `_cc` | unconditional repair at module top |
| `quality/tests/test_presence_coordinator.py:109` | `_cc` | unconditional repair at module top |
| `quality/tests/test_safety_coordinator.py:114` | `_cc` | unconditional repair at module top |
| `quality/tests/test_snap1_at_detection_snapshots.py:143` | `_cc` | unconditional repair at module top |
| `quality/tests/test_v450_d2_migration.py:83` | `_cc` | unconditional repair at module top |
| `quality/tests/test_v450_d4_arbitrage_ev.py:82` | `_cc` | unconditional repair at module top |
| `quality/tests/test_v4713_sleep_state_zone_presence_trust.py:501` | `_cc` | unconditional repair at module top |
| `quality/tests/test_v471_fixup_d2_d3_d4.py:118` | `_cc` | unconditional repair at module top |
| `quality/tests/test_v473_baseline_preset_editor.py:127` | `_cc` | unconditional repair at module top |
| `quality/tests/test_v47x_dynamic_preset.py:129` | `_cc` | unconditional repair at module top |
| `quality/tests/test_v47x_ev_tou_hardening.py:154` | `_cc` | unconditional repair at module top |
| `quality/tests/test_v47x_weather_manager.py:135` | `_cc` | unconditional repair at module top |
| `quality/tests/test_v5100_music_following.py:135` | `_cc` | unconditional repair at module top |
| `quality/tests/test_v5110_optimizer_hardening.py:133` | `_cc` | unconditional repair at module top |
| `quality/tests/test_v5_7_1_energy_precool.py:138` | `_cc` | unconditional repair at module top |
| `quality/tests/test_websocket_api.py:73` | `_cc` | unconditional repair at module top |
