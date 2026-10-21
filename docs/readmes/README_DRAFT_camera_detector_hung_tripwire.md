# DRAFT — Camera detector-hung trip-wire (version assigned at deploy)

Card: CAMERA-SILENT-PRODUCER-TRIPWIRE-1. Plan: `docs/planning/PLANNING_camera_detector_hung_tripwire.md` Rev 2. Tier 2.

## What changed
The shipped camera_input_dark trip-wire catches Frigate going *down* (person sensors unavailable). It cannot see a
*hung detector*: every sensor stays available, and the Frigate fleet `detection_fps` stat stops changing. This
release adds one optimizer evaluator, `camera_detector_hung`, that pages NM when that stat holds the same numeric
value for 15 min of observed time past boot settle.

- Entity resolved through the entity registry: platform `frigate`, domain `sensor`, unique_id ending
  `:sensor_fps:detection` (live today: `sensor.frigate_detection_fps_2`). Per-camera fps sensors (`..._detection`)
  do not match. Zero or several matches: inert, one INFO log `camera_detector_hung_inert_unresolved`
  (Protect-only installs land here).
- Value and first-seen time tracked in RAM. Any non-numeric state resets the dwell. `last_changed` is never read.
- One finding per episode per process lifetime (`dedup_key=("camera_detector_hung","fleet")`), cleared when the
  value changes. A restart or CM rebuild during a long hang re-pages after about 18 min (accepted).
- Exempt from the per-cycle findings cap and from the HIGH-to-digest defer, through one shared tuple
  `_FLEET_ONESHOT_KINDS`, also used by camera_input_dark.
- `binary_sensor.ura_coordinator_manager_camera_input_dark` gains `detector_frozen_s` and `detector_hung_fired`
  attributes. Its on/off meaning is unchanged.

Knobs: `CAMERA_DETECTOR_FROZEN_S = 900` (const, rung 1, fitted from the D0 probe: 3 x 5.0 min longest healthy run;
`<= 0` disables). `CAMERA_DETECTOR_FPS_UNIQUE_ID_SUFFIX = ":sensor_fps:detection"` (const, registry match key).

## Live acceptance (prospective)
| # | Criterion | Discriminates |
|---|---|---|
| L1 | After restart, `binary_sensor.ura_coordinator_manager_camera_input_dark` shows `detector_frozen_s` mostly < 60 and `detector_hung_fired: false` | Resolved and tracking. If it stays 0 always, check the log for `camera_detector_hung_inert_unresolved` (resolution failed) |
| L2 | **REQUIRED, operator-run, daytime only (never while the house sleeps):** staged detector pause. Pause or stop the Frigate detector so the process, status and camera fps stay up. Record whether `sensor.frigate_detection_fps_2` (a) freezes, (b) goes `unavailable`, or (c) oscillates. (a): a `camera_detector_hung` NM page must arrive within 900 + 300 s. (b): camera_input_dark fires and this check stays silent. (c): this check cannot see the hang; record it and park the card per plan §10. Restore Frigate (`docker restart frigate`) right after | First measurement of the hang mechanism. D0 could not see one inside recorder retention. The cycle does not close without this row |
| L3 | 7-day disposition: `notification_log` rows for `camera_detector_hung` = 0 absent a hang; any row coincides with zero person-sensor transitions over the same window | No false fire on ordinary days (I2) |
| L4 | No `Optimizer evaluator 'camera_detector_hung' raised` warnings in the log | Evaluator healthy in the real cycle |

Validation results: to be written back here after the restart.
