# Universal Room Automation — VibeMemo

*Last updated: 2026-09-26 | Version 4 | Contributors: ojiudezue*

**Previously…** Version 3 ([vibememo_v3.md](vibememo_v3.md), to 2026-08-17) told the June → mid-August story: the Optimization Coordinator write-flood rollback, the cloud-first battery pivot, and the night the guest oracle turned out to be dead. Versions 1–2 hold the earlier detail. The per-user trail is [users/ojiudezue/vibememo.md](users/ojiudezue/vibememo.md) (current) and [vibememo_v1.md](users/ojiudezue/vibememo_v1.md) (full, to entry 147). This version keeps the standing decisions with their reasons, compresses Aug–Sep, and records the HVAC reset of 2026-09-25/26.

## What URA is

A Home Assistant custom integration running ~43 rooms across 5 house zones and 3 HVAC zones, with domain coordinators for Presence, Energy, HVAC, Safety, Security, Music Following, Notifications and Optimization. It drives rooms from fused occupancy (motion, mmWave, BLE, cameras), controls battery, EV and HVAC for cost, and signals across coordinators. One operator, one install — no backward-compatibility scaffolding.

## Standing decisions and why

- **Single DB writer** (one queue, one connection; WAL reads). This ended "database is locked". Per-channel write-VOLUME review has been standing since the Optimization Coordinator saturated the queue and forced a rollback. → [001](users/ojiudezue/entries/001_db_single_writer_architecture.json), [021](users/ojiudezue/entries/021_optimization_coordinator_v5_shipped_writeflood_incident_remediation.json)
- **Battery control is cloud-first, forever; telemetry is local-first.** Enphase fw 8.3.x accepts local writes and ignores them, and control ran dead for ≥7 days unnoticed. Every write is verified against the cloud oracle. → [028](users/ojiudezue/entries/028_marathon_ev_deadband_cloud_first_writes_wave_dashboards.json)
- **Energy trust:** SmartHub > Emporia/SPAN > Envoy for cumulative; SOC is Envoy, never SPAN. Emporia is the permanent solar-follow grid primary, with the local Envoy stream as fallback — an operator trust ruling, not a speed argument. → [003](users/ojiudezue/entries/003_energy_measurement_trust_hierarchy.json), [147](users/ojiudezue/entries/147_envoy_stream_trust_and_emporia_primary.json)
- **House zones ≠ HVAC zones.** One thermostat zone maps to several house zones by design.
- **Automation vs safety bound.** Users can disable automation; max-runtime and shed caps transcend every toggle.
- **Change control is tiered by blast radius.** Regression-prone work gets three framing-disjoint reviews; delicate shared primitives add an adversarial-completeness pass plus an operator checkpoint. Mutation drills are executed. Call sites need their own wire-in anchors — a tested helper proves nothing about its callers. README live-validation tables are written back after every deploy. Empirically load-bearing: most shipped-incident-class bugs were invisible to the builder's green suite.
- **Measure before you build; producer AND consumer; verify before you work.** A one-shot probe over existing history comes before design. Every value is traced both to how it is made and who reads it. Every card, memo and README is a claim until checked against code or live data. Each rule was coined after a specific miss (failover-map rescope, census double-count, stale memos). → [029](users/ojiudezue/entries/029_measure_before_build_failover_rescope.json)
- **Operator decisions are fixed by implementation, never overturned by adjudication.**
- **Model tiering:** strong models for judgment; planner, builder and reviewer on opus-5.5, since opus-5 built the wrong thing and ignored instructions. → [146](users/ojiudezue/entries/146_hvac_live_room_gate_restores_operator_rule_opus55.json)

## Aug → Sep, compressed

**Guest/census (08-16).** Guest mode's only safety check had never run in production — two bugs in twenty lines hidden behind a fail-open `return False`. The lesson became a CLAUDE.md gate: ask how a value is *made*, not just who reads it. Suite serialization became a hook, not a rule. → [054](users/ojiudezue/entries/054_guest_census_fuller_pass_dead_oracle.json)

**Identity (09-04/05).** Measurement overturned face-first identity (door-crossing face attach ≈0%). The design became BLE-primary with face corroboration, built by extending the existing resolver, with centralised face-suppression as a hard fail-safe. → [089](users/ojiudezue/entries/089_identity_fusion_ble_primary_producer_and_failsafe.json)

**Attain (09-09/10).** A plan to modulate charge_from_grid died on physics: ~35-min actuation lag against a 5-min tick. Every other lever also failed. Decision: no code, accept ~$140–270/yr. The EV onset "bug" was really a parent-entry reload storm; its fix was held until root-caused. → [112](users/ojiudezue/entries/112_reload_storm_rootcause_onset_symptom_fix_held.json)

**The suite and HVAC's signal (09-15).** The test suite had been unrunnable (a loop-policy crash hid it), and task-leak detection had been inert all along. Separately, HVAC was consuming *lighting* occupancy (a 6–8 min clearance), so zone_3 conditioned hallways for people already gone. → [123](users/ojiudezue/entries/123_suite_unblock_and_leak_detector_blind.json), [124](users/ojiudezue/entries/124_hvac_room_zone_decoupling_and_success_def.json)

**HVAC step 4 (09-16/18).** v5.103.7 gave HVAC its own occupancy: hallway exclusion, per-room tail-holds, and reset-only night protection (an empty established zone retreats even if someone is home elsewhere). The v5.103.8/.9 follow-ups added knobs, "why away" attribution, and an occupancy gate on the D5 duty-cycle limiter — a URA energy heuristic that had been forcing occupied zones to away during coast.

## The HVAC reset (2026-09-25/26)

Two nights of wrong claims — about 15, each now in a corrections ledger — forced a forensic restart. The findings:
- **Zone 1's strands** were URA trusting a status-lagged `manual` from the Carrier integration after its own borrow returned correctly: `preset_mode` comes from the slow status poll, `hold_activity` from the prompt config feed. URA then locked itself out, and infinite holds kept it there — ~25 h over 5 days. [144](users/ojiudezue/entries/144_hvac_zone1_strands_are_status_lag_selflockout_not_bryant.json)
- **URA had been wrongly cleared** because its activity log never records temperature writes.
- **The occupancy fast path** — HVAC reacting to occupancy between 5-min ticks — was designed and never built.

The operator consolidated ~25 cards into four workstreams: **W1** one thermostat definition per *brand* (write, borrow/return, and read the true hold state), **W2** occupancy truth (the live-room gate, then the fast path, then a still-sleeper night hold), **W3** energy-aware HVAC, **W4** closure. **`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` is now mandatory reading before any HVAC work** — the code-verified snapshot every agent reads first so this drift does not recur. [145](users/ojiudezue/entries/145_hvac_arc_four_workstreams_state_of_play_read_first.json)

## Open questions

- W1 Stage A's write log: does it confirm the status-lag lockout as the dominant strand cause before the Tier-3 brand definition is built?
- Night still-sleeper corroboration (in-suite BLE, radar micro-blips) without regressing to "anyone home".
- Reducing zones 2/3's Bryant schedules so URA is the only controller.
- Envoy stream as a third SOC tier: pending trust run 2 plus a device-completeness guard.
- PWA commercial track: auth hardening before any non-operator user.
