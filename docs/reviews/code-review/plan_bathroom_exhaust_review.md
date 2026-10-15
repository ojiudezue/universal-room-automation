# Plan review — PLANNING_bathroom_exhaust_occupancy_and_resend.md (Tier 2, adversarial)

Commit reviewed: 989cfc48c. Not HVAC; presence read limited to `_became_occupied_time` producer sites.
Enumeration re-run: humidity-fan writes = automation.py:3363, 3385, 3446, 3510, 3544 only; `humidity_venting_enabled` sole caller coordinator.py:5424. Plan table holds.

**Verdict: FIX-REQUIRED (plan edits before build).**

| # | SEV | Plan § | Evidence | Fix |
|---|---|---|---|---|
| 1 | CRIT | D3.9 / I4 | No-humidity room has NO off emitter. The presence window is a HOLD (automation.py:3525-3530), not an OFF. The OFF branch is humidity-driven (:3540). With humidity=None the dwell fan only stops at max-runtime, then latches cap-suppression. | Add an explicit dwell-OFF: fan dwell-fired AND vacant AND window expired (or never armed) → turn_off + clear anchors. State it in I4. |
| 2 | CRIT | D3.3/4 | `dwell_fired` requires `not fan_is_on`, so from the next tick on, `on_trigger` is False in a dry room with a sensor. The OFF branch then fires at `timeout` (:3541-3549) while the room is still occupied. Dwell re-fires on the next tick. Result: on/off oscillation every `timeout` (a new spam path). | Split into `dwell_satisfied` (occupied AND elapsed ≥ dwell, which holds ON while occupied) and the transition. Block the humidity OFF while `_humidity_dwell_fan_on_at` is set and the room is occupied. |
| 3 | HIGH | D3.9 | The window arms only if `presence_runtime_enabled and wet_room` (:3486). A non-wet room with dwell=True never arms, so it falls into #1. | Gate dwell on wet_room, or arm the window independently for dwell. |
| 4 | HIGH | D3.6 / ask (b) | The Powder Matter sensor holds about 4 min, plus the URA occupancy timeout. A 20-s handwash keeps `_became_occupied_time` running past 60 s. Every visit fires, which defeats "number-2". | Measure dwell against motion-active time, or require dwell > sensor hold. Probe the recorder for Powder visit durations first (measure-before-build). |
| 5 | HIGH | D2.4 | Manual-off detection is "anchor ON, probe OFF". With `blocking=False` (:3514), the probe reads OFF on the transition tick, and a Shelly drop reads unavailable/off. Both get labeled manual and suppress re-asserts for 30 min, which contradicts I2(b). Not FAN-MANUAL-1 semantics: that one is oracle-backed (hvac_fans.py:343/686). | Detect only on an observed on→off state change with a non-URA context. Treat unavailable as a relay drop, never as manual. |
| 6 | HIGH | D1 + D2 | Sleep-off (:3385) emits turn_off EVERY tick, untransitioned. D1 extends that to master-off rooms. Not enumerated as a spam site. | Gate on `fan_is_on` / probe-on. |
| 7 | MED | D3.7 | `humidity <= off_threshold` (:3464) crashes on None. The plan's `elif` fix must come first. Also list :3424, :3495, :3517, :3538-3540, :3551 as readers to guard. | Enumerate every reader explicitly. |
| 8 | MED | ask (d) | The interim automations.yaml:1956-1990 (Powder) is a second writer. D1 alone unblocks Powder humidity venting at deploy. HA's 7-min-vacant turn_off would be read as "manual" (#5). | Ship Powder dwell=False until cutover, or disable the HA automation at deploy, not after. |
| 9 | LOW | ask (a) | The handler is called every tick even without a sensor (coordinator.py:5420). Tick = 30 s + jitter (:685), so dwell can fire as late as about dwell+30 s. | AC "±1 tick" OK; state it. |
| 10 | LOW | D1.1 | Back-compat kw for an internal helper is churn. | Drop it. |
