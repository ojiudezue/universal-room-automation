# AUDIT: config/options flow performance (2026-11-05 15:3x CST, live v5.103.103)

Read-only. No code edited, no form submitted; every probe flow was DELETEd.

## 1. Measured (REST POST /api/config/config_entries/options/flow, median of 3, wall ms incl. schema serialization)
| Entry | menu | slowest steps |
|---|---|---|
| Garage B (room) | 6 | climate 16, lighting 10, sensors 8, energy 6 |
| Living Room | 16 (outlier, 1 sample) | sensors 9, lighting 7, climate 7 |
| Ziri Bedroom | 8 | climate 10, lighting 9, sensors 9, devices 8 |
| Master Bedroom | 8 | lighting 9, sensors 9, climate 8 |
| Kitchen | 9 | sensors 8, climate 8, devices 7 |
| Stair Closet | 6 | sensors 8, devices/lighting/climate 6 |
| Coordinator Manager | 12 (menu) | energy 4, optimization 4, presence 2, hvac/safety/security 1 |
| Integration entry | 1 | global_sensors 8, camera_census 8, energy_sensors 6, perimeter 6 |
| Zone Manager | 10 (menu) | zpick_0/1/2/4 2 each |

Every step is under 20 ms. There is no server-side slowness in the options flows. Caveat: the REST call did not produce the TRIMMED menu (always 12 steps, no `show_all_settings`, with `show_advanced_options` true or false). So `_step_has_non_default_values` (config_flow.py:4397-4404, 4683) was NOT exercised. Estimate only: <=9 hidden steps x the 2-10 ms step render above, i.e. <=~60 ms. Unmeasured. Note HA docs say `show_advanced_options` is deprecated and always True (contributors.home-assistant.io/core/integrations/flow-steps/), so the trim path may effectively never run live.

## 2. Code findings (ranked)
1. `_get_area_entities` (config_flow.py:1313) iterates ALL registry entities per call (`ent_reg.entities.values()`, ~1325-1360). The live registry has 28,540 entries. 17 call sites, ALL in the create ConfigFlow (class at 1197): 1859-1883, 2657-2668 (12 calls in a row), 2760-2763, 3442, 3676-77. Fix: build a per-flow `{(area, domain): [...]}` index once per step (single pass), or cache on the flow for the step. Gain: about 12x fewer scans on the sensors/devices confirm step. I did not measure this path (it needs a create flow). The ms figure is an estimate and unknown.
2. Menu factory-render shim (4639-4660): constructs a new OptionsFlow and builds each hidden step's full schema just to read defaults, on EVERY menu render. Defaults are static per (step, room_type). Fix: memoize `_collect_schema_defaults` result in a module dict keyed by (step, room_type). Gain: removes <=60 ms (est.) from every menu render, with no behavior change.
3. `_get_ai_task_entities` (10724): `hass.states.async_all()` scan, fine at this size. Use `hass.states.async_entity_ids("ai_task")`, which is O(domain). Trivial gain.
4. `_rank_area_candidates` (1399+) re-resolves registry entries per entity; minor (3 call sites).
5. No sync file/DB I/O was found in config_flow.py (grep open/sqlite/read_text: nothing real). Registry scans are in-loop but are pure memory ops, so there is no blocking-I/O risk. The zone-delete sweep (12265+) is O(registry) but runs once and is not on a render path.

Conclusion: operator-felt slowness is NOT from options-flow render time. Likelier suspects are loop stalls from CM/parent reloads (see _cflow_timing.py docstring) or frontend rendering of large entity selectors. Unmeasured.

## 3. HA docs
- profiler.start: `seconds` (default 60), admin-only, writes a `.cprof` and a `callgrind.out` into the config dir (https://www.home-assistant.io/actions/profiler.start/). View with SnakeViz, gprof2dot or KCachegrind. The profiler integration is already installed (1 match in core.config_entries).
- profiler.set_asyncio_debug exists (https://www.home-assistant.io/actions/profiler.set_asyncio_debug/). Blocking-op guidance: https://developers.home-assistant.io/docs/asyncio_blocking_operations (it redirects to contributors.home-assistant.io/core/internals/blocking-operations/, which I did NOT fetch).
- Flow-step guidance: https://contributors.home-assistant.io/core/integrations/flow-steps/. It has no flow-performance guidance beyond progress tasks.

## 4. Profiling proposal
EXISTING: `_cflow_timing.py` (CONFIG-FLOW-SLOW-ONBOARDING-1) already wraps every `async_step_*` and logs `CFLOW-TIMING ENTER/EXIT elapsed_ms` at WARNING, gated by the module constant `CONFIG_FLOW_TIMING=True` (line 49). It also tracks autodetect calls/ms. I found no CFLOW lines in the logs I could reach (no /config/home-assistant.log; journald grep returned 0), so whether they emit is unverified.
(a) Zero code: Developer Tools > Actions > `profiler.start` {seconds: 120}, open the options flow, click through the heavy steps, then load the `.cprof` in SnakeViz and look for `config_flow.py` frames.
(b) Code change (proposed only): downgrade ENTER/EXIT to DEBUG and emit one WARNING only when elapsed_ms exceeds a threshold. Knob: Number-ladder rung 1 (module constant `CFLOW_SLOW_MS=250`), because it is diagnostic only and not an operator policy. Overhead is two monotonic() calls per step. No new file is needed; edit `_cflow_timing.py`. Also log the menu render separately, since the `async_step_init` wrapper already covers it.
RECOMMEND: (a) now, if the operator still sees a slow flow. (b) only the log-level and threshold tweak, because the WARNING-on-every-step noise is the real defect. Do not build more instrumentation: measurements show nothing to find server-side.
