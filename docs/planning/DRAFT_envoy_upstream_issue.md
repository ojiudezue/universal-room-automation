# DRAFT - NOT POSTED - for operator review

## Recommendation: comment on existing issue, do not file new

Issue https://github.com/home-assistant/core/issues/181243 ("enphase_envoy: unhandled RuntimeError: Session is closed in coordinator background tasks leaves integration dead until restart", open, integration: enphase_envoy, assigned to bdraco and cgarwood) already covers:
- the closed-session RuntimeError (leg 2 here),
- setup stuck in `setup_in_progress` and bootstrap-stage-2 timeouts (leg 1; nkinkade 2026-10-08 on 2026.9.4, chlodwig42 2026-10-13 on 2026.10.1).

Related work named in that thread: pyenphase PR #503 (v4.0.5), core PR #182473 (bump to 4.0.5), core PR #183172 (starts `/home` request after startup; per catsmanac awaiting review). A separate new issue would fragment this. Suggested: post the text below as a comment. If maintainers prefer a separate issue for the "setup never times out" leg, split it then.

Before posting: re-check #183172 status and whether coordinator.py changed since 2026-10-14 (claims below were verified against `dev` on 2026-10-14).

---

## Proposed comment / issue body

### The problem

Two related failures on enphase_envoy, observed on a real install (HAOS, one Envoy, local polling).

**1. Config entry setup hangs indefinitely with no log line and never times out.**
On 2026-10-14 at 08:33 local, at boot of HA 2026.10.1, the Envoy config entry stayed in `setup_in_progress` with no log output. It never timed out. Reload, disable and enable requests queued behind it and did nothing. The device was reachable the whole time (ping OK, `/info` returned HTTP 200). Only a full HA restart recovered it (about 32 minutes later, 09:05).
The boot also had a 131 s event-loop stall caused by a different integration. That may have been the trigger, but a stalled loop should not leave a config entry in setup forever. Whatever the trigger, setup needs an overall time budget so it fails with `ConfigEntryNotReady` and retries. This matches what catsmanac proposed on 2026-10-09 (overall budget during probe) and the 276 s setup reported by chlodwig42.

**2. `EnvoyClientClosedError` is a `RuntimeError`, so the #181243 fix does not reach the coordinator's handlers.**
pyenphase PR #503 (v4.0.5) raises `EnvoyClientClosedError` on a closed session. In pyenphase, `class EnvoyClientClosedError(RuntimeError)` (src/pyenphase/exceptions.py, line 103 on main) while `EnvoyError(Exception)` is at line 8. It does not subclass `EnvoyError`.
In core, `homeassistant/components/enphase_envoy/coordinator.py` (dev, checked 2026-10-14) handles `except EnvoyError` at lines 181, 202 and 383 (including `_async_try_refresh_firmware`, line 197). A `RuntimeError` subclass is not caught there. Searching core for `EnvoyClientClosedError` finds only the version-bump PR. As far as I can tell the new exception therefore still escapes as "Task exception was never retrieved". I have not confirmed whether `_async_fetch_and_compare_mac` is wrapped; at the time of my earlier audit (2026-09-25, 2026.9.2) it had no try/except, and I have not re-read it on current dev.
Note: I have not established that this exception is the cause of the dropouts below. Only that the handler gap exists.

**3. Availability dropouts (recorder data).**
Entity `sensor.envoy_<serial>_battery`, counting transitions to `unavailable` per local day:
- 2026-09-18 to 09-20 (on 2026.9.x, before 9.4): about 110-160 complete down/up cycles per day (220/324/223 total transitions).
- 2026-09-22 to 09-27 (2026.9.3): 120 / 109 / 120 / 52 / 15 / 83 down-events per day.
- After updating to 2026.9.4 (09-28, 09-29): 10 and 19 per day, with one outage of 232 minutes that matched the stuck-setup shape.
- Unavailable transitions per day on the battery sensor (recorder): 10-07: 1, 10-08: 8, 10-09: 8, 10-10: 4, 10-11: 12, 10-12: 6, 10-13: 4. On 10-14 the setup hang above; after the restart at 09:05 and again at 17:26, 0 drops for the rest of the day (the 17:26 restart reported data within ~2.5 min).
- Around 2026-09-27 to 10-01, a drop at about 23:05 local each night lasting about 1 h 45 m. It did not recur on 10-02, so I do not claim a pattern.
The flaps were not correlated with battery charge or discharge activity. Typical outages are 15 s to 10 min with a long tail of 1-2 h. Note the issue text says the entry "does not self-recover"; mine mostly recovers by itself and only sometimes sticks in setup.

### What version of Home Assistant Core has the issue?
2026.10.1 (setup hang, 2026-10-14). Dropouts also seen on 2026.9.2, 2026.9.3 and 2026.9.4.

### What was the last working version of Home Assistant Core?
Unknown. I do not have a known-good version.

### What type of installation are you running?
Home Assistant OS

### Integration causing the issue
Enphase Envoy (`enphase_envoy`)

### Link to integration documentation on our website
https://www.home-assistant.io/integrations/enphase_envoy/

### Diagnostics information
[OPERATOR: download from Settings > Devices & services > Enphase Envoy > Download diagnostics, and review for the serial and IPs before attaching. Not attached here.]
Environment: Envoy firmware [OPERATOR: fill, e.g. D8.3.x], pyenphase [OPERATOR: fill per version], Python 3.14, Envoy reachable at 192.168.x.x (redacted). Envoy serial redacted (`<serial>`).

### Example YAML snippet
N/A (UI config; options include disable_keep_alive: true).

### Anything in the logs that might be useful for us?
Setup hang: there was no log line from enphase_envoy during the hang.
Earlier dropouts (2026-09-25, core log, repeating): traceback through `enphase_envoy/coordinator.py:201 _async_try_refresh_firmware` -> `pyenphase/envoy.py:233 setup` -> `pyenphase/firmware.py:123 setup` -> `firmware.py:81 _get_info`, ending in "Task exception was never retrieved" / `RuntimeError: Session is closed`. About 25 such errors per flap and no `UpdateFailed` lines.
[OPERATOR: attach a debug-log excerpt for the 10-14 boot if available; redact IPs and serial.]

### Additional information
- Possible contention: a second local client (an Envoy-to-MQTT add-on) was running during part of the September data. It was stopped on 2026-09-28, and the rate fell but did not reach zero, so it is a confound rather than a cause.
- The integration is the only thing touching the Envoy API from HA; no custom component reloads or calls it.
- Suggested fixes: (a) a total time budget on setup/probe so it raises `ConfigEntryNotReady`; (b) catch `EnvoyClientClosedError` (or `RuntimeError`) in `_async_try_refresh_firmware` and `_async_fetch_and_compare_mac`, or have pyenphase raise an `EnvoyError` subclass.

---

## Addendum 2026-10-18 (overnight pass) - fresher numbers you may want in the comment

Source: `docs/planning/AUDIT_envoy_reliability_recount_and_witness_reconcile.md` section 3.1 (HA recorder, `sensor.envoy_482543015950_battery`, restart-adjacent episodes excluded). Since the host moved to Ethernet and HA's GC pauses were tamed on 10-15, short blips nearly stopped (24 in 5 days down to 2 in 3 days), but the integration now goes down for hours at a time: 587 min (10-15 17:38 to 10-16 03:25), 714 min (10-16 06:43 to 18:37), and another opened 10-17 23:08. Our own notes from 10-16 say that during one of these the Envoy's `/info` endpoint answered while the authenticated `/ivp/pdm/device_data` call hung, and a gateway reboot was needed. That fits leg 1 here (setup / first refresh with no timeout) better than random network loss, so it is worth one sentence in the comment: "after mitigating host-side stalls, the remaining failure is multi-hour hangs, consistent with a missing timeout in setup/first refresh."

Still to fill before posting (operator): Envoy firmware version, pyenphase version from the running core, a debug-log excerpt covering one long hang. Re-check core PR #183172 status first.

---

## Revision 2 (overnight 2026-10-31) — stronger evidence on 2026.10.4; recommend posting THIS part

Source: `docs/planning/AUDIT_envoy_core_fix_2026_10_4_match.md` "Night 1 on HA 2026.10.4" (operator-approved debug capture 10-30 22:54-23:35) + recorder read 2026-10-31 02:0x CDT.

**Recorder (sensor.envoy_<serial>_battery, HA 2026.10.4):** unavailable 2026-10-30 23:04:56 -> back 23:42:02 (37 min). The same Envoy's stream-based entity (separate integration, `/ivp/...` path) stayed live the whole window.

**Suggested comment text (new paragraph for #181243, or a separate issue "one hung endpoint blanks all enphase_envoy data" if maintainers prefer):**

> On 2026.10.4 (includes #183172) I still get a nightly outage at ~23:00-23:05 local, so that PR does not cover it. With debug logging for `homeassistant.components.enphase_envoy` and `pyenphase`, the Envoy itself stays responsive: `/ivp/meters` and `/ivp/meters/readings` keep answering in 0.1-0.9 s throughout. Only `/production.json?details=1` degrades: reply time rose from 1.1 s to 4.5-5.0 s over 22:55-23:00, last success 23:00:02, then every request (30 between 23:05 and 23:35) failed with `SocketTimeoutError: Timeout on reading data from socket` at the 45 s read limit. Because that endpoint is fetched inside the single coordinator update, each update fails after ~230 s (`Finished fetching ... in 233.6 seconds (success: False)`, `EnvoyError aiohttp ClientError Timeout on reading data from socket`) and every entity goes unavailable — including battery SOC and meter data that come from endpoints that were still answering. The outage ended on its own after 37 min. Request: per-endpoint failure isolation in pyenphase/the coordinator (keep meter/ensemble-derived data when `production.json` times out), and/or a shorter timeout for that endpoint so one slow legacy endpoint cannot blank the integration. Fixed clock time suggests an Envoy-side nightly job; firmware: <operator fill>.

Operator fills firmware + pyenphase version before posting. Items 1-2 of the original draft are older and weaker; post Revision 2 first.
