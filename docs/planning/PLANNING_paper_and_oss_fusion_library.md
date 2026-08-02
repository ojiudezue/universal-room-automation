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
- CameraResolver cycle deployed + census cutover flipped + ≥2 weeks live validation (the paper's
  evaluation section needs the live numbers).
- Operator go on IP posture (what is gifted vs retained).

Recall: "fusion paper queue"
