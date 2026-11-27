# v5.108.41: alert when a message channel goes dead (NM-IMESSAGE-OUTBOUND-DEAD-1)

Released 2026-11-27. One restart, done while the house was awake (state `guest`). PATCH bump.

Cards: NM-IMESSAGE-OUTBOUND-DEAD-1.

## Why

iMessage sends failed every time from 2026-11-22 17:12 to 2026-11-27 02:43. A Cloudflare "Always Use HTTPS" 301 on the
BlueBubbles host turned each POST into a body-less GET, and BlueBubbles answered 404 "Chat does not exist". Nobody was
told for 4.5 days: the other channels delivered, and `notification_log` marks a multi-channel row `delivered=1` when any
channel worked. The outage itself was fixed on the HA side (a new BlueBubbles config entry on the LAN host, operator
received a URA message at 02:44). This release adds the alert that would have caught it.

## What changed

`domain_coordinators/notification_manager.py`. Per message channel (pushover, companion, whatsapp, imessage):

- **Failure clock, persisted.** `_update_channel_health` now keeps `failing_since` (first failure after the last
  success), `consecutive_failures` and `alerted_at`, saved in a Store `universal_room_automation.nm_channel_dead`. It is
  written only on transitions (first failure, episode open, recovery), never per send, and survives restarts. NM holds
  one Store object, so saves land in order. A corrupt or unreadable Store starts clean instead of stopping NM.
  Failures seen before the Store loads are buffered and merged (earliest `failing_since`, counts summed).
- **Episode open.** When a channel has at least 3 failures and 6 h since its first failure, NM always creates the HA
  notification `ura_nm_channel_dead_<channel>` and an `nm.channel_dead` anomaly row, then sends a HIGH alert through the
  stuck-signal helper, keyed per outage `(channel, failing_since)` with the title "Notification channel dead:
  <channel>". `alerted_at` is set only when the send goes out, so a send dropped in quiet hours is retried on the
  channel's next failure. An in-memory guard stops the alert from re-entering when it routes to the dead channel itself.
- **Close.** The first success dismisses the HA notification and clears the clock, which re-arms for the next outage.
  A channel turned off in options is cleared on setup or reload.
- `channel_status` attributes now show `failing_since` per channel.

Where the alert lands under today's settings: the phone app (companion floor is HIGH) and the HA notification. WhatsApp,
Pushover and iMessage take CRITICAL only. In quiet hours (22:00-07:00) the push waits until morning; the HA notification
and anomaly row do not.

## Knobs

| Knob | Default | Rung | Note |
|---|---|---|---|
| `NM_CHANNEL_DEAD_ALERT_H` | 6 | module constant | hours of total failure before the alert; **0 turns the feature off** |
| `NM_CHANNEL_DEAD_MIN_FAILURES` | 3 | module constant | minimum failed sends in the episode |
| stuck-signal kill switch | existing | config | `CONF_STUCK_SIGNAL_NM_ENABLED` silences every stuck-signal alert, not just this one |

## Review

Tier 2. Plan review FIX-PLAN (per-outage key instead of the helper's per-day latch; re-entry guard), amended before build.
Build reviews A and B both SHIP, one MEDIUM each, fixed in `83b1e70a7`: validated restore, and one Store per NM. Full
suite on the fix-up: 23889 passed, 0 new failures. Record: `docs/reviews/code-review/v5.108.41_nm_dead_channel_alert.md`.

## Known limits

- Perimeter's direct notify (`perimeter_alert.py:4446`) bypasses NM and records no channel health.
- Provider-side silent drops on pushover/companion have no failure signal, so they are not detected.
- No "channel is back" message.

## Validated 2026-11-27 (restart 11:48)

Read over `ssh ha` with the supervisor API, because the HA MCP server was down this session. The Marketplace install
used its websocket commands `marketplace/repository/refresh` and `marketplace/repository/install`.

| Criterion | Result | Evidence |
|---|---|---|
| New code installed and running | PASS | `update.universal_room_automation_update` `installed_version` = v5.108.41; `/config/custom_components/universal_room_automation/manifest.json` version v5.108.41 |
| NM loads with no errors | PASS | Core log from 11:40 through the 11:48 restart to the check: zero `ERROR` lines from `universal_room_automation`, none mentioning `notification_manager` or `channel_dead` |
| `channel_status` shows `failing_since` | PASS | `sensor.ura_notification_manager_notification_channel_status` = `ok`; pushover, companion, whatsapp and imessage each show `status: ok, failures: 0, failing_since: null` (tts, lights and panels carry no `failing_since`, as designed) |
| No open episode in the Store | PASS | `.storage/universal_room_automation.nm_channel_dead` absent (written only on a first failure) |
| No dead-channel HA notification | PASS | no `persistent_notification.*channel_dead*` entity |
| Alert path (threshold, restart, quiet-hours retry, self-route, second outage same day) | in-suite only | 25 tests in `quality/tests/test_nm_dead_channel_alert.py`. Inducing a 6 h channel failure on the live house is not acceptable |

Boot note: `last_success` is null on every channel right after restart. It is in-memory and fills on the first send.
