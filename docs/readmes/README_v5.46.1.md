# v5.46.1 — Hotfix: Fused Camera Sensor Boot Re-Resolve

## The bug (found in v5.46.0 live validation)
`CameraPersonDetectedSensor` resolves its `room_cameras` at entity-add time,
which during boot runs BEFORE Frigate MQTT / UniFi Protect finish setup. The
empty (or partial) resolution was cached (`_fusions=[]` is `not None`) with no
retry path — the fused sensor and the fan-veto camera leg stayed inert after
EVERY restart until a manual config-entry reload. Live-reproduced on Study A
(post-boot `no_sources`; correct `single_source/medium` after reload).

## The fix
When the entity is added while HA is not yet fully running
(`hass.state is not CoreState.running` — includes the `starting` window), a
one-shot `EVENT_HOMEASSISTANT_STARTED` listener clears the cache and re-runs
resolution + subscriptions UNCONDITIONALLY — a boot resolve can be empty OR
partial (one camera platform up, another still loading), so the retry is not
gated on emptiness. Cleanup via `async_on_remove`; unsub nil'd first in the
callback. fan_veto needs no change — it reads the fused sensor's live state.

## Review
Two framing-disjoint reviews (A correctness / B lifecycle+test-authority),
verdicts SHIP-WITH-FOLLOWUP / SHIP. Folded in-cycle: A-MED partial-resolution
undershoot, A-LOW starting-window miss, A-LOW nil-first, B removal-race
comment. Both reviewers and the orchestrator ran independent source mutations
(guard inversion, cache-clear removal, emptiness-gate re-add) — all red.
Known accepted residual: if a camera platform is STILL not ready when
STARTED fires, the one-shot is spent — recovery = reload the room's config
entry (rare; bounded-retry rejected as overbuild).

## Suite
7926 passed / 34 failed = pre-existing baseline, zero drift. 7 anchor tests.

## Live Validation — prospective
- **Live:** next restart: INFO "added during boot (... configured cameras ...)
  scheduled re-resolve on EVENT_HOMEASSISTANT_STARTED" then INFO "re-resolved
  after HA started: 1 cameras / 1 sources" for Study A.
- **Live:** `binary_sensor.studya_room_device_camera_person_detected` shows
  `agreement != no_sources` WITHOUT any manual reload post-restart.
