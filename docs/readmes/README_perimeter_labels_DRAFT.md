# Perimeter alert switch names + options-flow parity (DRAFT, unversioned)

Card: PERIMETER-SWITCH-LABELS-AND-FLOW-PARITY-1 (Tier 1).

## What changed
- New device names. Entity ids and unique ids stay the same.
  | Entity | Old name | New name |
  |---|---|---|
  | switch.ura_perimeter_zone_agreement_demote | Quiet Off-Property Alerts | Lower Road Alerts |
  | switch.ura_perimeter_single_source_demote | Quiet Single-Camera-System Alerts | Lower Single-Sourced Alerts |
  | switch.ura_perimeter_egress_known_xcorr_gate | Door Alerts Only for Strangers | Unknown Person Door Alert |
  | switch.ura_perimeter_identity_followup | Door Alert Name Follow-Up | Add Names to Alerts |
  | select.ura_perimeter_vlm_gate | Perimeter AI Person Check | AI Person Check (options shown Off / Watch only / On; stored values still off / shadow / enforce) |
- New House options step **Perimeter Alert Filters** with all five settings and helper text. It saves by merging into the existing options, so values set from the device switches are kept. All five keys were already in `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`, so a save does not reload the integration.
- **Lower Single-Sourced Alerts** (the switch and the flow field) only exists when at least one camera has both a Frigate and a Protect leg. This is decided from the entity/device registries by `CameraResolver.has_frigate_and_protect_camera()` (wrapped by `perimeter_fp_gates.dual_nvr_present`). On a one-system install the switch is not created and the field is hidden. The gate is already inert there: it only demotes when both families are live on the camera (reason `single_nvr`).

## Acceptance
- Test: `quality/tests/test_perimeter_switch_labels_flow_parity.py` (16 tests: names, pinned ids, select option labels, flow round-trip, switch-written values kept, one-NVR and two-NVR installs, resolver detection, reload-suppress membership).
- Pre-deploy check against the live registry: 19 cameras have both a Frigate and a Protect leg, so the live single-sourced switch stays.
- Live (post-restart): the five entities show the new names with unchanged entity ids; Settings > URA > Configure > Perimeter Alert Filters shows five fields with the current switch values; saving it does not reload the integration.

## Not done
- On an install that loses its last dual camera, an already-registered `switch.ura_perimeter_single_source_demote` stays in the registry as an orphan. It is not removed automatically, because a false negative at boot would delete the live entity.
