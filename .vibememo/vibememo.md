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

## 2026-11-13/14: names are not identity; dead inputs under live plans

The identity arc made the registry rule standing: no inferring platform, device, person or room from an entity name. → [298](users/ojiudezue/entries/298_registry_not_name_guessing.json) Unused AI rules and music following get fixed and ship on, with no shadow ladder. → [300](users/ojiudezue/entries/300_fix_not_retire_no_shadow_mode.json) Overnight 11-14 found why every per-room Bluetooth distance died on 10-20: the wall-panel proxies trip an all-or-nothing early return in Bermuda. → [305](users/ojiudezue/entries/305_bermuda_per_scanner_dead_panel_proxies.json) That dead input sat under the music repair's planned confidence gate, which as written would have followed no one. → [306](users/ojiudezue/entries/306_music_gate_on_dead_ble_confidence.json)

## 2026-11-16: quieting keys must match what a duplicate is

Interior vision ship 2 (describe a room by text, Foyer fisheye unwarped in URA) shipped as v5.108.32 with the face fallback held to the 0.75 naming bar, which leaves it Bluetooth-only until interior face confidence rises. The paging cap proved itself live on a recovered 4 a.m. page. Validation also found NM boot-settle collapsing distinct stuck-sensor kinds under one hazard type while the stuck latch recorded the dropped page as sent: the same shape as the circling de-dup miss two days earlier. → [329](users/ojiudezue/entries/329_boot_settle_swallows_distinct_stuck_kinds.json)

## 2026-11-20: evidence of who acted, and of who arrived

Two attribution fixes on the same day. A face at the door proves who walked through it, not that they just came home, so entry notices say "arrived" only when that person's phone arrival edge is in the window and "came in" otherwise → [343](users/ojiudezue/entries/343_arrived_vs_came_in_and_room_rules_built.json). Room rules had the mirror problem: HA drops a call's context after 5 s, so a slow shade would read as undone by hand. Reversal is now judged by which way the target's state moves, and review C's mutations pinned 14 untested trust sites → [344](users/ojiudezue/entries/344_room_rules_reversal_judged_by_state_not_context.json). The overnight pass also found the board two cards behind shipped code → [343](users/ojiudezue/entries/343_overnight_board_drift_shipped_cards_left_planned.json).

## Open questions

- OC: which fix types earn R1 first, and the promotion evidence for R2.
- Moving the forecast sensors onto the dwell model, and whether each beats persistence.
- Halo NM delivery (S1b/S2).
- Reserve governor and inclement rebuild (freeze versus wind as the outage cause).
- Envoy stream A/B/A; HVAC still-sleeper corroborator; reducing zones 2/3's Bryant schedules.
- PWA: auth hardening before any non-operator user.

The arrival engine then shipped as v5.108.33 under option B. Start and welcome scene act now. Stop and pause are held to a conservative ownership rule until a live MA test, because stopping chosen music is the costly mistake; v6.0.0 is anchored to that test. → [330](users/ojiudezue/entries/330_arrival_engine_ships_option_b.json)

One correction: the merge meant to bring in the boot-settle fix had merged master instead, so v5.108.33 went out without it while its README said otherwise. A grep of the release tag for the new constant caught it before install, and the fix ships as v5.108.34. Ancestry has to be checked against the fix commit's own hash, not the merge's. → [331](users/ojiudezue/entries/331_merge_took_master_not_the_fix.json)


The 11-17 overnight pass took the default it had offered on the false 'impossible room move' flood (about 230 a day since 11-14): flag a move only when a camera covers that room, built to review and held for an attended deploy. → [333](users/ojiudezue/entries/333_overnight_takes_default_a_on_transit_flood.json)

One counseling note from the same pass: feed and card times were typed from a felt sense of elapsed work and ran up to 48 minutes ahead of the real clock. They were rewritten; edit scripts now read the clock themselves. → [334](users/ojiudezue/entries/334_overnight_timestamps_must_come_from_date.json)


**2026-11-17, door direction scored.** On the operator's 27 grades no direction instrument passes: the tracker is 10/19 and biased (every miss reads an entry as an exit), and the one strong variant was tuned on the same clips. So the count path ships (P3-D2) and vision direction is recorded, not trusted (P3-D3), until per-door reps clear the P3-D6 bar; the front door needs exits graded. Same day, music following stopped following TV audio after all 7 handoffs failed on a Sonos TV stream → [336](users/ojiudezue/entries/336_door_direction_scoring_no_instrument_passes.json).


**2026-11-17, only proven code supersedes correct code.** The operator ruled that hardened Tier-3 code is not rebuilt and other rewrites need a measured defect and a proven replacement. Re-measured, the layer cleanup's leaks were correct code (the 'HIGH' security leak never fired while armed), so 4 builds became 1 (fail-open identity vetoes, a portability bug). The layer's value was already banked: every feature since 11-14 builds on it → [337](users/ojiudezue/entries/337_only_proven_code_supersedes_correct_code.json).


**2026-11-17, the ledger never got to be known.** The crossing ledger keeps its state in RAM and needs a 15-minute empty house to become known; our two-restarts-a-day ship cadence reset it so often that it was known ~34 minutes in 3.5 days, which also made the interior floor plan moot until the ledger survives restarts → [338](users/ojiudezue/entries/338_restart_cadence_keeps_ledger_unknown.json).


**2026-11-18, the harness learns from always-on agents.** One day showed five harness gaps (shared worktree with a mutator, noisy no-news pings, follow-ups only in-session so a release slipped 8 hours, stale memory index, decisions as chat lists); the operator approved all five fixes: one writer per tree, report once / stay quiet, due: on cards surfaced at session start, a Decisions queue on the board, and a memory archive. Same day the garage lock showed the cost of trusting stale state: it stopped reporting on 11-15 and the sweep kept believing 'locked' → [340](users/ojiudezue/entries/340_harness_adopts_always_on_patterns.json).


**2026-11-19, closing out the arc.** On 'finish the arc... for things unblocked', a sweep closed 13 arc cards, parked 6 low-probability ones with triggers, and shipped the 4 ready fixes plus the lock-freshness fix in v5.108.38; open siblings fell from 21 to 7, all blocked on operator input or data. An HA core update restarted HA mid-sleep, so unplanned updates now count against the one-restart-a-day budget → [342](users/ojiudezue/entries/342_arc_close_sweep_and_restart_budget.json).


**2026-11-20, the board drifts behind the code.** The overnight pass checked ground truth before work and found two cards that shipped in v5.108.8 still marked planned; both were closed on the README evidence. The lock-page wording residual was built display-only and sent to review, with no deploy → [343](users/ojiudezue/entries/343_overnight_board_drift_shipped_cards_left_planned.json).


**2026-11-20, 'arrived' means the phone arrived.** The first live named arrival from the old face path was wrong (a resident already home walked in from the garage), so entry notices now say 'arrived' only with that person's own arrival edge and 'came in' otherwise; S1 non-anchors now record why. Unified room rules was built the same day and waits on review → [343](users/ojiudezue/entries/343_arrived_vs_came_in_and_room_rules_built.json).


**2026-11-22, met in letter, failing in practice.** The overnight soak-exit sweep found two features whose checks looked passed: music following picked the right speakers but all 13 moves failed, because AirPlay music isn't in a Music Assistant queue (fix: use the MA path only for real MA queues), and Garage A door-camera entries could never get an indoor path, because the path map has no route from that camera (fix: one map line, waiting on approval). It also rejected the previous night's 'clean' suite runs, whose baseline was broken, and re-proved the three review fixes on a green develop (23,846 pass, 0 fail) → [345](users/ojiudezue/entries/345_overnight_findings_airplay_ma_path_and_doorbell_lite_path_gap.json).


**2026-11-22: what 'house average' means.** Oji approved the filtered house-average sensors and defined the scope by use: the average is the temperature of conditioned living space. Equipment closets are infrastructure (Study A Closet reclassified by setting), and garages are out because they are unconditioned. URA keys this on configured room type, not names, and leaves the unfiltered average alone for the HVAC consumers that already depend on it.
Oji then pointed out the garages are also equipment rooms (EV chargers, shop tools). The answer was the per-room infrastructure switch, not a room-type change: it takes their loads out of waste and cost figures while they keep behaving as garages. Room type governs behaviour; the switch governs energy accounting.
With two release windows already missed, Oji cleared a restart that evening, and the release went out without the room-rules screen picks rather than slip a third time. The picks change how rules are written, not whether the shipped executor works, so they lead the next release.


**2026-11-23 overnight, the perimeter fixes did not cut the alert count.** Pushes ran 60/day over the last week against 69/day before the 11-08 gate work, almost all still high/critical, and the 'Lower Road Alerts' check has never fired because its zone sensors were never set. The arc now waits behind the one perimeter settings ask already on the operator's queue, and that ask now carries the numbers. No new page was sent. Three shipped cards closed on live evidence. The Claude AI Task is locked until 12-01 → [350](users/ojiudezue/entries/350_overnight_perimeter_fp_volume_not_met_park_behind_ask.json).
