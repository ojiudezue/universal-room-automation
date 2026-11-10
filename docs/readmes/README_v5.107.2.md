# v5.107.2: SNAP-1 Frigate event snapshots fetched over the internal URL

Card: PERIMETER-FRIGATE-SNAPSHOT-CAPTURE-NEVER-1. Tier 1 hotfix. Root cause: `docs/planning/AUDIT_perimeter_snapshot_capture_2026_11.md`.

## Problem

SNAP-1 tier 1 (`frigate_event`) never produced a file. All 1,825 files in `/media/ura/snapshots` had the live-grab name shape. `_http_get_bytes` built its URL with `_absolutize`, which prefers `hass.config.external_url` (`https://haos.phalanxmadrone.com:8123`). From the HA host that URL times out, so every fetch overran the 2 s `PERIMETER_SNAPSHOT_HTTP_TIMEOUT_S` and the capture fell through to `live_grab`. The same path over the internal URL returns 200 in about 0.05 s.

## Fix A: internal base for server-side fetches

- New `PerimeterAlertManager._internal_base_url()` calls `homeassistant.helpers.network.get_url(hass, allow_external=False, allow_cloud=False, prefer_external=False)`. The signature was checked in the installed HA source (`helpers/network.py:118`). When no internal URL exists it returns None, and the fetch is skipped. It never falls back to the external URL.
- `_http_get_bytes` now resolves relative paths against that internal base.
- `_absolutize` is unchanged. `_absolutize` call sites, classified:

| Site | Use | Base |
|---|---|---|
| `_resolve_snapshot_url_and_delay`, Frigate event URL | outbound link (`snapshot_url` for Pushover/WhatsApp/NM) | external (unchanged) |
| `_resolve_snapshot_url_and_delay`, `entity_picture` fallback | outbound link | external (unchanged) |
| `_http_get_bytes` (SNAP-1 tier 1 download) | server-side fetch | **internal (changed)** |

## Fix C: no stale event id on a second walk-past

- A Frigate `end` message now records the ended id per camera in `_frigate_ended_event_id`. The id cache itself is not erased, so the NM link path still resolves after the event ends (this keeps the 2026-08-07 hotfix).
- `_try_capture_frigate_event` refuses an id that has already ended. At a new rising edge, an ended event belongs to the previous track. Capture then falls to `live_grab`.
- A new `new` or `update` id replaces the cache, so a second walk-past fetches its own event.
- No new number. The ended check is a plain identity test.

## Not done (by instruction)

- Fix B (wait or re-read the id cache at the edge, for the roughly 39% of alerts whose edge comes before the bus `new`). Measure the tier-1 hit rate after A first.

## Tests

In `quality/tests/test_snap1_at_detection_snapshots.py`, all `test_v5_107_2_*`:

- The fetch uses the internal base, with `allow_external=False`.
- With no internal URL there is no fetch, and the external URL is never used.
- The outbound `snapshot_url` (Frigate and `entity_picture`) stays on the external URL.
- An ended id is not fetched.
- A live id is fetched (control case).
- A second walk-past fetches the new id.
- The NM link survives `end`.

Mutation drills: each of the following turned a specific named test red, and the source was restored afterwards.
- fetch through `_absolutize`
- drop `allow_external=False`
- fall back to external
- internal base on the outbound site
- neuter the ended check
- neuter the ended producer

## Live validation

### Validated 2026-11-10

Read 2026-11-10 ~02:10-02:20 CST, HA running v5.108.1 (manifest), restart 01:04 CST. Read-only. This release (v5.107.1 through v5.107.6) first ran at that restart. Logging caveat: the integration logger is `log_level: WARNING`, so every INFO marker in these criteria is never written to the HA log, and `ha_get_logs` cannot show it. Log absence is therefore NOT evidence for or against these criteria.

| Criterion | Result | Evidence |
|---|---|---|
| New Frigate-event-shape file after a Frigate-leg person alert | NOT-YET-OBSERVABLE | No Frigate-leg person alert since restart. `notification_log` rows after 07:04 UTC are `[audit]` only (newest id 26384, 07:05 UTC). The last perimeter alert is 00:37 UTC, before the restart. `/media/ura/snapshots` (1771 files) has newest mtime Nov 9 20:35, so no file since restart. |
| Shape discriminator (`<cam>_<epoch>.<frac>-<suffix>.jpg`) | NOT-YET-OBSERVABLE | Frigate-shaped files already exist from before the restart (e.g. `g5_bullet_1794271039.302052-hm87fc.jpg`, Nov 9 18:37). The shape alone cannot prove this fix. A post-restart file is required. |
| INFO ledger `PerimeterSnapshot: wrote=... engine=frigate_event` | NOT-YET-OBSERVABLE (log-invisible) | `_LOGGER.info` (`perimeter_alert.py:4075`) under a WARNING logger. |
| Pushover/WhatsApp links still external | NOT-YET-OBSERVABLE | No alert since restart. |
| Non-Frigate legs stay live-grab | NOT-YET-OBSERVABLE | No alert since restart. |

**Verdict 2026-11-10:** 0 PASS, 0 FAIL, 5 NYO. Needs one Frigate-leg person alert after restart, then one ssh `ls -t` of the snapshot directory.

