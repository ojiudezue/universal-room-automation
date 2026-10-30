# AUDIT: does core PR #183172 (shipped 2026.10.2) fix our nightly 23:06 Envoy drop?

Prober run, read-only, 2026-10-30 ~06:45 CDT. Did NOT read the STATE_OF_PLAY docs (not HVAC/presence). Verdict: **NO-MATCH on the 23:06 drop; PARTIAL on the Sept log signature.**

## 1. What PR #183172 fixes (gh pr view/diff, merged 2026-10-15T19:47Z)
Title: "Handle Enphase envoy Session is Closed in background tasks". Related to (does NOT close) issue #181243. Files: `__init__.py`, `coordinator.py`, tests.
- Failure fixed: background tasks (firmware refresh, MAC verify, token refresh) outliving config-entry UNLOAD/reload -> `RuntimeError('Session is closed')` "Task exception was never retrieved". Trigger = entry unload/reload while a timer-spawned task runs.
- Changes: tasks via `config_entry.async_create_background_task` (cancelled on unload); catch `EnvoyClientClosedError` and `RuntimeError` when session closed AND entry not LOADED, in `_async_try_refresh_firmware` and `_async_fetch_and_compare_mac`; timers start only on entry state LOADED; log-arg-order fixes.
- No pyenphase bump in the PR (manifest unchanged by it). Does not touch the polling `_async_update_data` / UpdateFailed / availability path.

## 2. Installed (ssh ha, `sudo docker exec homeassistant`)
- HA core `homeassistant.const.__version__` = 2026.10.4. pyenphase 4.0.6 (pip list; manifest `requirements: pyenphase==4.0.6`).
- Changed lines present: `coordinator.py:11` imports `EnvoyClientClosedError`; `:217` and `:272` `except EnvoyClientClosedError`. Fix is in the running install (HA restarted 06:23:14 CDT 10-30, recorder `homeassistant_start`).
- All of 10-23..10-29 ran on 2026.10.1 (starts 10-23 04:42, 10-24 x3, 10-25, 10-26 10:09), i.e. WITHOUT the fix.

## 3. Our failure, from evidence
Recorder `sensor.envoy_482543015950_battery` (state transitions, CDT):
unavailable -> back: 10-23 23:06:26->23:20:52 (14m); 10-24 23:06:05->23:26:38 (20m); 10-25 23:06:43->23:29:26 (23m); 10-26 23:06:06->23:26:46 (21m); 10-27 23:06:47->23:25:45 (19m); 10-28 23:09:29->23:30:09 (21m); **10-29 23:06:40->10-30 00:01:27 (55m)**. One window per night, every night, no other drops 10-23..10-30 06:23.
- Scope at 23:04-23:10: all native `enphase_envoy` entities (envoy_482543015950_*, encharge_*, enphase_dry_contact_relay*) go unavailable together = whole-coordinator failure (entities went `unavailable`, not stale).
- Other integrations at ~23:00-23:06: cloud cameras/images (camera.sonoffwindow, roborock map, generac hero image) blip every night ~23:01 (12 transitions each; cloud-ish, cause unknown). The 8311 ONU sensors (41 entities) blipped 23:06:05 on 10-27 and 10-29 but NOT 10-23/25; ONU uptime is continuous (3751965 -> 3752097 s), so no ONT reboot; ONU recovered in ~1 min, Envoy in 14-55 min. Not a LAN-wide event.
- Logs: `docker logs --since` 10-29 23:00-23:40 (journald-backed) contains ZERO lines matching enphase|pyenphase|envoy (2429 lines since 22:00 total, so the window was not empty). So the nightly drop emits no WARNING/ERROR at default level: no Session-is-closed traceback, no UpdateFailed. Caveat: debug logging is off, so the exact exception text is UNKNOWN; token expiry/HTTP timeout/Envoy-side maintenance cannot be separated from logs.
- Exact exception for the 23:06 drop: UNKNOWN (not logged). Mechanism ranking from what is observed: periodic (same minute nightly) + whole-coordinator + 14-55 min + silent. That is a schedule-driven event (Envoy-side nightly job/reboot/Wi-Fi/ethernet path, or token re-auth cycle), not an unload race. Not distinguishable as Envoy-side vs token without debug logs.
- `enphase_realtime`: custom integrations enphase_realtime and enphase_ev are installed (loader warning 06:31). I found no entities with an `enphase_realtime` id in the recorder (LIKE '%enphase_realtime%' returned none), so I could NOT verify the "it stayed up" claim; unknown. Note `sensor.envoy_stream_*` (MQTT witness) has been `unavailable` since 10-23 04:40:02 (HA start 04:42), so no local witness comparison exists for these nights - the add-on stream is itself dead, a separate finding.

## 4. Verdict
- 23:06 nightly drop: **NO-MATCH.** PR fixes task-cleanup on unload/reload; our drops are coordinator-wide availability loss with no unload (no entry reload logged; URA never reloads it per memory), no log errors, fixed clock time. Falsifier: a drop tonight with PR code present proves it.
- Sept 110-160 drops/day: **PARTIAL (signature only).** Sept log showed 249x `RuntimeError: Session is closed` at `coordinator.py:201 _async_try_refresh_firmware` (memory project_session_pickup_2026_09_23.md 1.2). The PR now catches that exact exception, so the log noise is removed. But memory 1.2 already established ~25 such errors per flap with ZERO UpdateFailed lines and that the flap mechanism was not established; the error can be a symptom of a closed session after a flap/reload rather than its cause. Since 10-15 (host to Ethernet, GC tamed - AUDIT_envoy_reliability_recount) flapping fell to ~0-2/day anyway, so the pre-fix 10-15..10-29 data cannot show the PR's effect; only post-10.4 data can.
- Residual: the PR is "a first step" per its own description; #181243 stays open.

## 5. Acceptance check (ready to run; CDT = UTC-5)
Fixed vs different: the PR cannot affect the 23:06 event, so expect it to RECUR. If tonight (10-30 23:06) shows no drop for ~7 nights, something else changed (host/Envoy/network) - credit unproven, check ONU/Envoy firmware. If drops recur at 23:06 with no log lines, failure unchanged (expected). Run via
`ssh ha 'sudo docker exec -i homeassistant python3 -' < script`:

```python
import sqlite3,datetime as d
c=sqlite3.connect('file:/config/home-assistant_v2.db?mode=ro',uri=True)
tz=d.timezone(d.timedelta(hours=-5))
mid=c.execute("select metadata_id from states_meta where entity_id='sensor.envoy_482543015950_battery'").fetchone()[0]
t0=d.datetime(2026,10,30,7,tzinfo=tz).timestamp()   # after 06:23 restart
prev=None
for ts,s in c.execute("select last_updated_ts,state from states where metadata_id=? and last_updated_ts>? order by 1",(mid,t0)):
    un=s in('unavailable','unknown')
    if un!=prev: print(d.datetime.fromtimestamp(ts,tz).strftime('%m-%d %H:%M:%S'),s)
    prev=un
```
Plus, within 23:00-23:40 each night: `ssh ha 'sudo docker logs --since <t0> --until <t1> homeassistant 2>&1 | grep -iE "enphase|pyenphase|envoy"'` (empty = silent drop; "Session is closed" = PR not effective; UpdateFailed text = real exception to capture). For exception text, enable debug logging for `homeassistant.components.enphase_envoy` and `pyenphase` before 23:00 (a change; operator decision).

## Orchestrator correction (2026-10-30)

Item 5's "no enphase_realtime entities in the recorder" is wrong. Its entities carry the `_2` suffix (`sensor.envoy_482543015950_battery_2`). Recorder during the 10-29 native outage (23:06:40-00:01:27): battery_2 was live except `unavailable` 23:14:27-23:22:07 (7.7 min) and 23:23:17-23:23:48 (31 s); it resumed at the prior value (35/34). On 10-21..10-27 it stayed up through every drop. So the fallback would have covered ~46 of 55 min that night; the 60 s reconnect settle handles the two reconnects. It is the first realtime dropout seen during a native drop; recheck the remaining nights after deploy.
