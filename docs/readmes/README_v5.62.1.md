# URA v5.62.1 — SECC-1 ordering hotfix: register the linker before announcing readiness

**Tier:** Hotfix (2-line reorder + a de-silenced guard + an ordering anchor test).
Found by the diagnostic instrument shipped in v5.62.0, ~40 minutes after that deploy.

## What was broken

`__init__.py` dispatched `SIGNAL_EXTERIOR_LINKER_READY` on the line **above** the
`hass.data[DOMAIN]["exterior_track_linker"] = ...` assignment. Every READY subscriber resolves the
linker out of `hass.data`, so all of them found `None` and returned — **silently**.

Consequence: `PerimeterAlertManager`'s deferred camera-allowlist install never ran, on any boot,
across **v5.59.0 → v5.62.0**. Three successive cycles hardened this path (subscribe to READY, warn
instead of no-op, add a boot-sanity guard) and none of them worked, because the signal was announced
one line too early. The silent early-return in the handler is *why* it stayed invisible — the
SECC-1 sanity WARNING could never fire either.

**How it was finally caught:** v5.62.0 added `allowlist_installed` / `allowlist_camera_count` to the
exterior open-tracks diagnostic specifically so the install would be verifiable from a sensor
instead of log-level surgery. Post-deploy the sensor read `allowlist_installed: false,
allowlist_camera_count: 0` — an instrument built to answer a question immediately answering it
"no". That is the cycle's real lesson: the observable was worth more than the three fixes.

## Fix

1. **Register before dispatch** — `hass.data[DOMAIN]["exterior_track_linker"] = ...` now precedes
   `_ads(hass, SIGNAL_EXTERIOR_LINKER_READY)`. Both subscribers (the perimeter allowlist install and
   the switch control-surface restore) can now resolve the linker.
2. **The guard no longer no-ops silently** — the READY handler's early return logs a WARNING naming
   which precondition failed (`linker_present=`, `cameras_staged=`). A guard that can silently do
   nothing hides exactly this class of bug.
3. **Ordering anchor test** — `test_linker_registered_in_hass_data_BEFORE_ready_signal_dispatched`
   asserts the assignment precedes the dispatch. A source-order assertion by necessity
   (`async_setup_entry` is not executable in the harness), but it pins a *relationship* rather than
   the mere existence of a string, and it fails the instant the statements are reordered.
   Orchestrator-verified: reverting to the buggy order turns it RED.

## Acceptance criteria

- **Live (the whole point):** post-restart, `sensor.ura_security_coordinator_outside_open_tracks_diagnostic`
  reports `allowlist_installed: true` with `allowlist_camera_count` matching the configured
  perimeter + egress cameras (12 were staged pre-fix).
- **Live:** no `READY handler fired but cannot install allowlist` WARNING.
- **Live:** interior cameras no longer open exterior tracks; off-list events land in
  `ignored_offlist_events` instead of being admitted.

## Live Validation

(prospective — replaced with the Validated table post-restart)
