# QUEUED — Paper + OSS Library: Multi-Modal Presence Cross-Correlation (BLE · PIR · mmWave · Cam-person · Cam-face)

**Operator directive 2026-08-01:** "I genuinely think this is unique IP and worth an abstracted
python or go library." Queue AFTER the CameraResolver cycle + census cutover complete (the system
should be fully shipped and live-validated before being written up). Status: QUEUED, not started.

## The thesis (what is actually novel here)
Not any single detector — the **cross-modal arbitration layer** built across 2026 cycles:
1. **Role separation by failure mode**: BLE = identity+continuity (noisy at room resolution;
   device≠person); PIR = high-precision motion edges (blind to stillness); mmWave = stillness
   coverage (fan/airflow-corruptible); Cam-person = location-anchored verification + strangers;
   Cam-face = identity binding for the camera layer (tri-state capability: usable/ambiguous/absent).
2. **Directional trust doctrine**: extend-not-create (BLE v5.22.0), sustain-requires-corroboration
   (mmWave demotion v5.42.0), divergence-downgrades-not-max-wins (census v5.43.0),
   accused-witness exclusion (a sensor cannot corroborate a decision about its own failure mode —
   mmWave under a fan, fan_veto v5.40.0).
3. **Path-level fusion**: the transit validator — BLE proposes room-to-room paths, camera
   checkpoints confirm/refute (+0.10/−0.15), faces bind identity, mismatches become anomalies.
   Review E's literature survey found no OSS equivalent.
4. **Physical-camera resolution across integrations** (CameraResolver): correlation ladder with
   operator ground-truth, family collapse for correlated detectors, capability-diversity preference.
5. **Verification methodology as part of the IP**: falsifiable invariants + per-limb mutation
   anchoring + probe-first acceptance fixtures (the D0 dry-run pattern).

## Doctrine additions (operator, 2026-08-06 — Ziri gym incident)

6. **Manual action as a fusion vector.** A human actuation (switch/fan
   flipped at the wall or app) is presence EVIDENCE: spatially anchored,
   instantaneous, unforgeable, decaying. Enters fusion like a motion
   edge (can extend/create occupancy with decay). Motivated by the
   2026-08-05/06 Exercise Room incident: mmWave-sole + fan-on demotion
   (D2) repeatedly released a still occupant to vacant and swept his fan
   — while his manual fan-on minutes earlier was ignored as evidence.
7. **Intent vs evidence separation (operator axis).** Split human-action
   signals into EVIDENCE (where people are: manual actuation, PIR edge,
   BLE direct) vs INTENT (what people want: media playing —
   `music_following_enabled` plumbing exists as prior art — scene
   selection, override switches). Doctrine: evidence may extend/create
   occupancy; intent NEVER creates occupancy but raises the bar for
   off-decisions (sweep veto weight) — extend-not-create generalized.
   Music-in-empty-room is the spoof case that forces the split.
7b. **Decay is first-class for BOTH classes (operator, 2026-08-06).**
   Evidence and intent both decay, and the ideas are only useful with
   well-chosen decay functions — likely different shapes per signal:
   a manual actuation decays from its event time over an
   expected-activity horizon (step-at-timeout or exponential); PIR
   edges already have timeout decay; media-intent anchors on the last
   human INTERACTION (start/skip/volume — each itself a manual-action
   evidence event), NOT on playback state: playback-continuing is a
   weak prior that decays even while playing (operator counterexample
   2026-08-06: Jaya's room plays music while empty), re-anchored by
   every interaction, and room-conditioned — strong in shared/activity
   spaces (gym), weak in bedrooms; per-room media-while-away priors
   are learnable from memory baselines;
   a CO2 rise would be a slow-onset/slow-decay sustain witness with
   ventilation confounds. The library's sensor-event interface should
   carry (class: evidence|intent, decay_fn, anchor_time) per signal —
   decay curves are where the tuning lives, so they must be explicit,
   named, and per-signal, not implied by code structure. NOTE: CO2 as
   witness is UNBUILT today (exists only in the safety-alert path);
   listing it here is design, not prior art.

8. **Sole-witness corollary (accused-witness sharpened).** Upgrading the
   accused witness (cheap wave-motion mmWave → zone-masked LD2450/FP2)
   fixes the physics, not the doctrine: one witness is still one
   witness, and D2 keys on room fan state, not sensor zones. Remedies
   are a second failure-mode-independent witness (BLE proxy, CO2) or an
   explicit per-room trust upgrade — never silent exemption.

## Deliverables (to scope when dequeued)
- **D-PAPER:** whitepaper/preprint-style write-up: architecture, doctrines with incident-grounded
  motivation (playroom phantom ×3, Study A fan loop, guest-laundering), evaluation from live data
  (demotion counts, divergence rows, veto counters, transit confirmation rates — the system logs
  its own evaluation corpus), related-work section seeded from Review E's 21 sources.
- **D-LIB:** extracted OSS library — HA-agnostic core (the arbitration/doctrine layer + resolver
  ladder as pure functions over an abstract sensor-event interface), thin HA adapter. Language:
  Python first (HA ecosystem gift), Go port optional later. License + naming TBD by operator.
- **D-GIFT scope:** what to give HA-land (a custom integration or helper library others can wire
  their own sensors into) vs beyond-HA (the abstract fusion core). Trademark/IP posture = operator
  decision before any publishing.

## Gates
- CameraResolver cycle deployed + census cutover flipped + ≥2 weeks live validation for the
  YOUNGEST surfaces only (census cutover, dual-host corroboration). Operator ruling 2026-08-06:
  accelerate via probe-first backfill — demotion counters (v5.42+), divergence rows (v5.43+),
  veto counters, transit rates, memory episodes are already weeks-old in the URA DB/recorder;
  one-shot read-only probes can build the evaluation tables NOW, architecture/doctrine sections
  need no numbers, and only the census-cutover column lands last.
- Operator go on IP posture (what is gifted vs retained).

Recall: "fusion paper queue"
