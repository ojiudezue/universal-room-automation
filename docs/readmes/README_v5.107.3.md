# URA v5.107.3: External-URL self-check

**Tier 1.** Operator, 2026-11-08: "make sure external url is always right." Per the operator's instruction, this has no kanban card.

## Why

HA's External URL was set to a stale `https://haos.phalanxmadrone.com:8123`, and requests to it timed out. Nobody noticed, because WhatsApp and iMessage attach the image file itself. Pushover and the companion app send a link built from `external_url` instead (`notification_manager.py` ~2352 and ~2430, `perimeter_alert._absolutize`), and those links were broken. The URL has since been corrected to `https://madronehaos.phalanxmadrone.com`. This release makes sure the next break gets noticed.

## What

- New module `external_url_check.py`. Once HA has started (`async_at_started`), and then every day, it reads `hass.config.external_url`. If the URL is set, it sends a GET to `<external_url>/manifest.json` from the HA host. The request uses HA's shared aiohttp session, has a short timeout, and carries no auth.
  - If the request times out, fails DNS or the connection, or returns a non-2xx status, the check raises the Repairs issue `external_url_unreachable` (WARNING, not fixable). The issue reads: "Home Assistant's External URL (<url>) is not reachable (<reason>); notification image links (Pushover, companion app) will be broken. Fix it in Settings → System → Network." It also logs a WARNING.
  - A 2xx response deletes the issue, so it clears on recovery.
  - If `external_url` is unset, the check does nothing and only logs at debug level.
- Wiring: the check starts from the integration entry's setup in `__init__.py`, right after the version check. Both unsubs (the started-listener and the daily interval) are registered with `entry.async_on_unload`. The interval is armed before the first probe awaits, so an unload during the probe still cancels it.
- This release reuses existing patterns and adds no new framework: issue create/delete follows `version_check.py`, and the started-then-interval scheduling follows `_schedule_ec_role_scan`.

## Knobs (rung 1, module constants in `const.py`)

| Knob | Value | Why |
|---|---|---|
| `EXTERNAL_URL_CHECK_INTERVAL_S` | 86400 | The URL rarely changes, so a daily check catches a break within a day at a cost of one tiny GET. |
| `EXTERNAL_URL_CHECK_TIMEOUT_S` | 10 | A healthy proxy answers in under a second. 10 s allows for a slow WAN hop without holding the socket for aiohttp's 300 s default. |

## Tests

`quality/tests/test_external_url_check.py` (12 tests) covers pass/delete, timeout, DNS error, non-2xx (404/502/301), the 199/200/299/300 boundaries, clear-on-recovery, unset no-op, deferral plus the daily interval plus unsub on unload, and the wire-in anchor through `async_setup_entry`.

Mutation drills: each neuter turns at least one named test RED. The drilled sites were the 2xx range, delete-on-pass, create-on-fail, the unset guard, the timeout kwarg, the probe path, interval unload registration, `async_at_started` deferral, the first check at start, and the `__init__` wire-in call.

## Live acceptance criteria

- **Live:** after restart, with the current URL `https://madronehaos.phalanxmadrone.com`, Settings → Repairs shows **no** "External URL not reachable" issue, and the log has no `External URL ... is not reachable` warning.
- **How to provoke one (optional):** set Settings → System → Network → External URL to an unreachable value (for example the old `https://haos.phalanxmadrone.com:8123`), then reload the URA integration entry or restart. Within about 10 s of start the issue appears. Put the correct URL back and reload or restart, and the issue clears. Otherwise it clears on the next daily tick.

## Not done

- No sensor attribute exposes the last check result. The Repairs issue plus the WARNING log are the surface. Add an attribute later if it's wanted.
- The check doesn't re-run immediately when `external_url` changes. The next restart, reload, or daily tick picks the change up.
