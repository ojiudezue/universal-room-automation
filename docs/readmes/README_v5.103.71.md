# v5.103.71: five Tier-1 fixes (zone delete, setup task, security re-fire, websocket, deploy ^C)

Cards: ZONE-DELETE-ORPHAN-HVAC-SENSORS-1, INIT-UNTRACKED-TASK-4211-1, SECURITY-REFIRE-INTRUSION-KEY-1, WS-SUBSCRIBE-SEND-OFF-LOOP-1, WS-SUBSCRIBE-SCHEMA-REALHA-1, DEPLOY-DUALPUSH-SIGINT-TRAP-1.

**Tier 1.** Reviews:
- The first three cards: `docs/reviews/code-review/overnight_2026-10-18_tier1_batch.md` (SHIP).
- The websocket and deploy fixes: `docs/reviews/code-review/tier1_ws_dualpush_2026-10-18.md`.

**Deploy risk: LOW.** No battery, HVAC or presence decision logic changes.

## Problem → solution

- **Zone delete left 4 HVAC sensors behind** (AC-reset and ramp/durability), and the delete preview undercounted them.
  - The four prefixes are now swept.
  - A delimited zone-id matcher replaces a bare `startswith` at the preview, delete and leftover-warning sites (`config_flow.py`). That also fixes a latent bug where deleting `zone_1` would match `zone_10` for every id-keyed family.
- **A setup task was not tracked.** The TOU-rejected stuck-signal notification task in `async_setup_entry` used an untracked `hass.async_create_task`. It now uses `entry.async_create_background_task`, so it is cancelled on unload or reload.
- **Security alerts never re-fired after cooldown.** The re-check looked for `intrusion`, but Security emits `intruder`.
  - `SECURITY_REFIRE_HAZARD_TYPES` now accepts both.
  - `investigate` is excluded on purpose, so a MEDIUM is not escalated to CRITICAL.
  - Inert live today: no producer emits `unknown_present` yet. The re-page-loop risk is recorded on SECURITY-CENSUS-UNKNOWN-WIRE-1.
- **The `ura/logs/subscribe` websocket push ran off the event loop.** `_send_on_loop` lacked `@callback`, so `hass.add_job` ran it in an executor thread. `@callback` is added.
- **The websocket schemas could break registration.** The `websocket_command` decorator received bare `vol.Schema` objects, which raise at import on HA 2026.2.3. They are now plain dicts, the decorator's documented form.
- **Ctrl-C during the deploy's Gitea mirror push** left the token-bearing remote URL in `.git/config` for up to 60 s. The push now runs in the background with `wait`. INT/TERM stop it, restore the clean URL and exit with 130/143 at once. This is a script change only; nothing changes in HA.

## Tests
- Websocket tests: 4 tests un-quarantined, so 19/19 now pass. Drills:
  - Dropping `@callback` turns 1 test red.
  - Reverting the schema form turns 4 tests red.
- `test_deploy_scripts.py`: 12/12 pass. The SIGINT test had been red whenever `gtimeout` was on PATH.
- The three overnight fixes: each has its own tests and mutation drills (see the review record).
- Full-suite name-diff vs a3f5b9dd9: pending, to be filled in before deploy.

## Live validation (prospective)
- Installed and loaded: manifest v5.103.71, all URA entries loaded, no new URA ERRORs.
- No `observability WS commands registration failed` warning in the system log.
- Zone delete, the setup-task path and security re-fire are not exercised by a restart. The proof for those is in the test suite.
