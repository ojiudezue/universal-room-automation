# Universal Room Automation — VibeMemo

*Last updated: 2026-10-21 | Version 4 | Contributors: ojiudezue*

**Previously…** Version 3 ([vibememo_v3.md](vibememo_v3.md), to 2026-08-17) told the June → mid-August story: the Optimization Coordinator write-flood rollback, the cloud-first battery pivot, and the dead guest oracle. Versions 1–2 hold the earlier detail. Per-user trail: [current](users/ojiudezue/vibememo.md), [v2](users/ojiudezue/vibememo_v2.md) (09-26 → 10-21), [v1](users/ojiudezue/vibememo_v1.md) (to entry 147).

## What URA is

A Home Assistant custom integration running ~43 rooms across 5 house zones and 3 HVAC zones, with domain coordinators for Presence, Energy, HVAC, Safety, Security, Music Following, Notifications and Optimization. It drives rooms from fused occupancy, controls battery, EV and HVAC for cost, and is being generalized for more homes.

## Standing decisions and why

- **Single DB writer**, with a write-volume review per channel since the Optimization Coordinator flooded the queue. → [001](users/ojiudezue/entries/001_db_single_writer_architecture.json), [021](users/ojiudezue/entries/021_optimization_coordinator_v5_shipped_writeflood_incident_remediation.json)
- **Battery control is cloud-first; telemetry is local-first.** Local writes were silently ignored for ≥7 days. → [028](users/ojiudezue/entries/028_marathon_ev_deadband_cloud_first_writes_wave_dashboards.json)
- **Energy trust:** SmartHub > Emporia/SPAN > Envoy; SOC is Envoy; Emporia is the grid primary by operator ruling. A missing number beats a wrong one: rejected energy days write NULL and train nothing. → [003](users/ojiudezue/entries/003_energy_measurement_trust_hierarchy.json), [231](users/ojiudezue/entries/231_solar_counter_flap_corrupts_daily_energy.json)
- **One reserve governor** at the `_result` chokepoint before any storm hardening, because ~25 branches applied their own floors. Storm doctrine: alert → local applicability → local forecast → decide. → [213](users/ojiudezue/entries/213_reserve_governor_first_inclement_doctrine.json)
- **HVAC:** read the state-of-play doc first. S1's manual guard became four gates. URA's energy actions win over person protection, and that protection survives restarts. Thermostat brands are auto-detected code profiles. → [145](users/ojiudezue/entries/145_hvac_arc_four_workstreams_state_of_play_read_first.json), [152](users/ojiudezue/entries/152_s1_manual_guard_superseded_four_gates.json), [169](users/ojiudezue/entries/169_thermostat_profiles_in_code_autodetected_generic_net.json)
- **Predictions must beat a trivial baseline before anything actuates on them** (see below). → [230](users/ojiudezue/entries/230_predictions_not_trustworthy_dwell_model.json)
- **Change control is tiered by blast radius:** three framing-disjoint reviews for regression-prone work, with an adversarial-completeness pass at Tier 3. Measure before building, verify claims before working, trace both producer and consumer, and fix the implementation rather than overturn an operator decision. → [029](users/ojiudezue/entries/029_measure_before_build_failover_rescope.json)

## Sep → mid-Oct, compressed

The HVAC reset (09-25/26) traced Zone 1's strands to real Carrier manual holds created after URA's own return and consolidated ~25 cards into four workstreams → [148](users/ojiudezue/entries/148_zone1_strands_real_manual_holds_not_status_lag.json). URA went multi-home, which unparked the thermostat-brand abstraction → [166](users/ojiudezue/entries/166_multi_home_rollout_generalize_thermostat.json). Bulk room onboarding shipped → [178](users/ojiudezue/entries/178_onboarding_phase2_bulk_rooms_coordinators_addons.json). Z-Wave moved to Z-Wave JS UI on a PoE radio → [188](users/ojiudezue/entries/188_zwave_control_plane_zwave_js_ui_mrw10.json). Bills moved to meter counters → [191](users/ojiudezue/entries/191_ec_billing_meter_counters_option_b.json). Census work was held until its inputs are fixed → [184](users/ojiudezue/entries/184_census_hybrid_inputs_first.json).

## 2026-10-20/21

- **v5.103.78 recorder churn:** diagnostic sensors stopped rewriting unchanged values every tick, cutting URA's recorder rows from ~20.1k to ~8.8k per hour. HA-side recorder excludes cut ~18k more.
- **v5.103.79 bill prediction:** SmartHub cost to date plus same-weekday pricing for the remainder, with tracked accuracy (15% error vs 32–43% for a straight line). → [228](users/ojiudezue/entries/228_v5_103_79_bill_prediction_uses_smarthub_cost_and.json)
- **v5.103.81 EC shutdown save:** HA never unloads integrations on stop, so EC now stops its timers and persists in a shutdown job, and nothing can actuate after the DB writer closes. → [229](users/ojiudezue/entries/229_v5_103_81_energy_state_is_saved_at_shutdown_and_.json)
- **v5.103.82 solar CT counter:** the Envoy lifetime counter flaps, which made daily solar 0.0 or NULL on 36 of 40 days. The monotonic CT counter replaces it. → [232](users/ojiudezue/entries/232_v5_103_82_daily_solar_uses_the_production_ct_cou.json)
- **v5.103.83 dwell-model anomaly sensor:** a predictions audit found nothing trustworthy, because the Bayesian model counts arrivals, not dwell, and is never scored against a baseline. The anomaly sensor was rebuilt on a per-room hour-of-week dwell model and replayed: median 0 fires/day. → [233](users/ojiudezue/entries/233_v5_103_83_occupancy_anomaly_sensor_on_a_room_dwe.json)
- **Halo wall panels:** a separate opt-in integration with a typed service API, live on 7 panels. Bridge 1.7.0 fixed colour reporting, because HA had been dropping the colour without the colour mode.
- **OC goes agent-first (critical):** static detectors were ~90% noise, while a manual reason-fix-verify loop found real faults. The OC becomes a nightly URA agent acting within risk tiers: R0 observe, R1 silent reversible fixes, R2 visible fixes only when promoted and never during sleep, R3 never alone. It uses each coordinator's existing paths; a unified request API was rejected on cost. → [234](users/ojiudezue/entries/234_oc_agent_first_risk_tiered.json)

## Open questions

- OC: which fix types earn R1 first, and the promotion evidence for R2.
- Moving the forecast sensors onto the dwell model, and whether each beats persistence.
- Halo NM delivery (S1b/S2).
- Reserve governor and inclement rebuild (freeze versus wind as the outage cause).
- Envoy stream A/B/A; HVAC still-sleeper corroborator; reducing zones 2/3's Bryant schedules.
- PWA: auth hardening before any non-operator user.
