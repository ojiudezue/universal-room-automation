# Universal Room Automation — VibeMemo

*Last updated: 2026-07-13 | Version 3 (full June detail preserved in vibememo_v2.md) | Contributors: ojiudezue*

## How This Started

URA is a Home Assistant custom integration managing ~40 rooms across 5 house zones with 7+ domain coordinators (Presence, Energy, HVAC, Safety, Security, Music Following, Notifications, Optimization). It automates room behavior from occupancy fusion, Bayesian prediction, energy optimization, and cross-coordinator signals.

## Load-Bearing Decisions (standing)

- **Single-threaded DB write worker** — all writes serialize through one asyncio.Queue + one persistent connection; reads on transient WAL connections. Ended the "database is locked" era; v5.16.2 made the worker-gap window lossless (buffer, don't raise). → [001](users/ojiudezue/entries/001_db_single_writer_architecture.json)
- **Energy measurement trust hierarchy** — SmartHub > Emporia/SPAN > Envoy for cumulative; Envoy primary for real-time; battery SOC = Envoy, never SPAN. → [003](users/ojiudezue/entries/003_energy_measurement_trust_hierarchy.json)
- **Battery CONTROL = cloud-primary, permanently; telemetry = local-primary** (2026-07-13 → [028](users/ojiudezue/entries/028_marathon_ev_deadband_cloud_first_writes_wave_dashboards.json)). Enphase firmware 8.3.x silently accepts-and-ignores local battery writes — control ran dead ≥7 days before URA caught it. All writes route through the cloud integration with same-leg command-state reads (W-5), self-heal re-dispatch, an unmaskable verification alarm, and local entities as a secondary witness. No failover design may ever re-demote control writes to local.
- **Every battery write is verified** — commanded ledger → 15-min cloud-oracle compare → reversion sweep → transition-latched anomalies → once/day NM per (surface, alert-type). Reusable for any actuator whose "accepted" signal is untrustworthy.
- **House zones ≠ HVAC zones** — one thermostat-keyed HVAC zone maps to N house zones by design; compound display names are legitimate merges, never zones to delete.
- **Automation vs safety bound** — venting/comfort is automation a user can disable; max-runtime caps are universal bounds transcending every toggle (v5.6.0 pattern for future safety bounds).
- **Model tiering** — expensive judgment, cheap labor: frontier model for orchestration + adversarial review framings; Opus for builders/planners (and, under trial, checklist review framings). Measured origin: builders burned ~1.6M tokens in one marathon while ~700k of reviewer tokens caught every shipped-incident-class bug. The pipeline catches builder mistakes; only a strong reviewer catches the rest.
- **Framing-disjoint review (Tier 2-DB/3) for all regression-prone work** — empirically load-bearing: the 07-12/13 session alone caught 7 CRITICALs + ~28 HIGHs post-build, zero shipped; every CRITICAL was invisible to its builder's green suite. Standing gates: mutation anchors that builders must EXECUTE (four false-anchor recurrences in one wave), worktree isolation for parallel builders (tree contention silently dropped committed-claimed hunks), pre-review baseline tags, README live-validation write-backs.

## Open Questions

- Degraded-arbitrage on cloud telemetry during sustained local-Envoy outages (operator-gated deliverable in the failover-map plan).
- Reviewer cost-tiering verdict after the next wave (first Opus datapoint: SHIP + one real catch, at Fable-average token cost).
- Commercial track gates: PWA auth hardening before any non-operator user; native iOS parked behind HACS ~100 installs.

## The June arc, compressed (full detail: vibememo_v2.md)

**v4.7.28–.33 (06-08):** EV off-peak ensure-on + day-boundary TOU (Bug Class #51: never assume a period is "ahead" without a midnight-crossing lookahead) → [018](users/ojiudezue/entries/018_v4728_v4729_ships_tier2db_policy_day_boundary_bug_class.json). The hygiene marathon fixed silently-dead features (compliance sensors pinned at 100; a motionless-occupant veto dead since ship because tests mocked the dict the same wrong way) and codified **verify-don't-assume against stale state** — sensitive ops read live sources at action time, never memos. → [019](users/ojiudezue/entries/019_v4730_v4731_v4732_marathon_zone_resolution_heatcool_span_prune.json), [020](users/ojiudezue/entries/020_v4733_af5_ttl_plus_optimization_coordinator_scoped.json)

**Optimization Coordinator (06-09/10):** scoped agentic-first with a six-rung autonomy ladder; shipped v5.0→v5.3 overnight — then **took the house down** via O(N)-per-cycle DB writes and was rolled back, fixed forward with batched persists after adversarial review found a second equal-sized write channel the first fix missed. Durable rule: write-VOLUME reviews enumerate every channel by table. → [021](users/ojiudezue/entries/021_optimization_coordinator_v5_shipped_writeflood_incident_remediation.json). The five-deploy marathon finished OC (routine model; autonomy knobs; the veto handshake made binding after shipping advisory-only) and set the model-tiering policy. → [022](users/ojiudezue/entries/022_v531_v534_marathon_oc_phase5_complete_model_tiering.json)

**Envoy decoupling + attainability (06-12/13):** a dead Envoy stranding all 40 entries exposed boot coupling (after_dependencies removed; RestoreEntity unavailable-coercion = Bug Class #52), and a live manual-arbitrage exercise measured Enphase's actuation constants, which became the `attain` phase — *"no solar reaching the battery → need for arbitrage."* Heaviest cycle ever (1 build + 4 fix-ups + 7 reviews) taught: when two builders fail the same requirement, prescribe the **mechanism**, not the behavior; mutation-anchored tests became a standing gate after review proved deleting the whole solar term stayed green. → [023](users/ojiudezue/entries/023_v537_v538_envoy_decoupling_attainability_redesign_marathon.json)

**06-13→07-04:** the three-cycle march (attainability ladder; HC pre-conditioning; load-shed ownership fix — the strongest 3-framing demonstration: A/B/C each found a *different* defect class in one diff) → [024](users/ojiudezue/entries/024_march_3cycles_oc_llm_config_inclement_weather_design.json); the inclement-weather reserve designed (event-type over severity as the classifier gate; hold bounded by the alert's own expiry — the anti-Enphase-over-hold thesis); bathroom-exhaust Tier 3 established the automation-vs-safety split and confirmed Bug Class #53 (computed-but-not-consumed) as URA's dominant failure mode → [025](users/ojiudezue/entries/025_bathroom_exhaust_humidity_unification_tier3_gate_boundary.json); the **silent-actuator failure class** surfaced and made visible — check device availability BEFORE suspecting URA → [026](users/ojiudezue/entries/026_ship_march_v560_v572_offline_actuator_visibility.json); and the HA 2026.7 overload was triaged to a duplicate linkplay integration — duplicate integrations over one device are latent load bombs a core scheduling change can detonate → [027](users/ojiudezue/entries/027_ha_2026_7_overload_reconcile_tier3_hardening.json).

## The marathon: "I wake to an uncharged car" → cloud-first battery control (2026-07-12→13)

→ [028](users/ojiudezue/entries/028_marathon_ev_deadband_cloud_first_writes_wave_dashboards.json)

**Act one — the dead band (v5.15.0, Tier 3).** The EV charge-start release gate compared SOC to the *static* reserve (10%) while the strategy parks the battery at its per-night *drain target* (15–40%) — two floors never reconciled (Bug Class #53 again); the release was unreachable most nights. Fixed by sourcing the floor from the emitter's actual commanded park, off-peak-gated (the first build applied it in all TOU periods, which would have disabled peak drain protection — reviews caught it). Proven live night one: the car charged from 00:12 on the exact restored stuck state that pre-fix held forever.

**Act two — the lie (v5.16.1).** Validation caught Enphase firmware 8.3.x *accepting* local charge-from-grid writes and never applying them — the local switch echoed "on" while the cloud, which the hardware obeys, stayed off. Recorder audit: control silently dead for at least the full 7-day retention window; every arbitrage window that week ran solar-only, every peak started underfilled. The cloud-first pivot (standing decision above) followed the same day, and the first *verified* battery write in URA's history landed at 12:40:31 — self-heal → cloud dispatch → Enlighten applied → status ok → 16.3 kW grid charge. The subtlest trap — the heal loop cancelling its own verification forever, masking the alarm in exactly its target failure mode — was caught in review before it shipped.

**Act three — the wave (v5.16.0) and the surfaces.** Five parallel cycles: the guest-latch fixed by evaluation *order* (deliberately no GUEST→SLEEP transition — real guests should hold the house awake); the empty-house veto rebuilt on a sustained-external-empty discriminator after all three reviewers independently proved the first build's predicate was a tautology; census false-guests killed via per-area BLE cancellation (+ kill switch; census hold 15→3 applied via a restart-window .storage edit after a running-HA edit was clobbered); the zone-delete name-collision guarded (and yesterday's live 5-hour HVAC-zone knockout retro-explained by a dead hass.data slot); pause hygiene incl. the operator-coined class *"stops are diligent, starts are lazy — every pause rule needs an every-cycle start evaluation, not just an undo of its own pause"* (L1 plugs got the level-triggered ensure-on L2 already had). Plus **URA 7**: a new fully-dynamic status-and-control dashboard (auto-entities + template cards; v6 preserved), and the **PWA** re-scoped as a separate, carefully-planned commercial track on its own custom WebSocket client — HAKit formally buried ("slow, like everything we built with hakit"). Queued with finished plans: the telemetry failover map (debounced trip, hysteretic return, auditable auto-built pairing map with diagnostics export + continuous cross-validation), PWA M2 control completion (with a prototype review that found dead decorative controls and missing numeric/hold-to-confirm primitives), and the observability WebSocket surface that finally gives the anomaly/activity logs a transport.

**Epilogue — the probe that rescoped the build (07-13 late).** → [029](users/ojiudezue/entries/029_measure_before_build_failover_rescope.json). Before the failover map's first line was built, the operator forced two moves: pair the local↔cloud entities *by hand* against live values ("before code does it a thousand times"), and *measure the gaps before building*. A 10-minute read-only recorder probe settled everything the plan had deferred to runtime instrumentation: the cloud's power values refresh only every 5–15 min upstream (freshness, not poll rate), which **rejected the two riskiest deliverables outright** (stale cloud power must never feed the drain-gate or arbitrage); the battery-power sign convention resolved itself from history (no live experiment); and the cloud "grid power" entity turned out to match *no transform of reality at all* — a broken upstream derivation a name-based auto-pairer would have admitted. The lesson was codified as a CLAUDE.md gate, **Measure Before You Build**: when a cycle's value depends on empirical properties of external data, the first deliverable is a one-shot probe over history that already exists — its output is scope, not telemetry. The hand-built pairing table is the acceptance fixture the eventual automation gets diffed against. The same evening also shipped the v5.16.3 persistence rider (whose framing-C review proved the restore path untested and forced executed-mutation fix-ups before deploy) and rebuilt URA 7's Rooms tab on the decluttering + room-face + auto-populating-popup architecture, zone-clustered, with URA's own occupancy sensors driving the room glow.

## The night that shipped nothing (2026-08-16→17)

→ [054](users/ojiudezue/entries/054_guest_census_fuller_pass_dead_oracle.json)

**Narrative gap, stated honestly:** this file's prose jumps from 07-13 to 08-16. Entries **030–053** cover
that span (through v5.78.0) and are the authority; the summary prose was never written and is NOT
reconstructed here rather than guessed at.

A small guest/census cycle — clamp a census that double-counted residents, make guest *rooms* lead instead
of the count — passed three framing-disjoint reviews, then its own fix-up introduced a HIGH, then an
operator-ordered fuller pass (three more framings) found that guest mode's only safety check had **never
run in production**: `_is_known_person_in_room` carried two independent bugs in twenty lines — a lookup
against a registry the person coordinator is never registered in, and a read of an attribute that exists
nowhere — short-circuiting on the first so the second stayed masked, with a fail-open `return False` making
it look defensive while being inert. The "known person → don't treat this as a guest" transition had not
fired since v4.7.2. Harmless while guest entry was `census OR rooms`; about to become false-guest-on-residents
the moment D2 made rooms the sole arm. Nothing shipped, and three regressions were stopped: a
false-guest-at-boot the fix-up itself created, the dead oracle, and an entire dedup cycle a ten-minute probe
proved would buy zero (BLE-cancel isn't broken code — 3 of 7 camera areas have no URA room and no interior
camera watches a bedroom; meanwhile 74.5% of over-count time had no live camera evidence at all, so *decay*
is the real cost centre).

Four lessons worth more than the diff. **Producer AND consumer** became a CLAUDE.md gate after the census
double-count showed every reviewer asking who *read* the count and nobody asking how it was *made* — and
then I violated it on my own fix-up, which is what created the boot HIGH. **Agreement is not verification:**
a builder and I both concluded "no guest rooms are designated" using the same wrong config key, and the
concurrence read exactly like confirmation; the real key had three rooms flagged, one of them a bathroom.
**A third hollow-anchor variant** — oracle-echo, where a test imports the production constant for its own
expected value, so detaching the constant leaves it green. And **mechanism over rule:** the suite runs four
minutes alone and forty overlapped, so serialization became a PreToolUse hook rather than another
instruction — which then blocked a build agent for an hour via a catch-22 (it matched the very `ps`/`kill`
commands its own error message told you to run) and a zombie with 0.01s of CPU. Both fixed, with the guard's
own deny path mutation-drilled. The operator's pace complaint was fair; the cause was never the reviews.
