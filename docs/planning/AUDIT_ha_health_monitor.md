# AUDIT: HA Health Monitor (`ha_health_monitor` v1.3.0): what exists, what matters

Date: 2026-10-13. Read-only research. Nothing on the HA host was modified.
Source audited: `/config/custom_components/ha_health_monitor_integration/` (Samba mount). There is no repo.
HA version is 2026.10.1. Registry size: 26,684 entities and 2,657 devices.

---

## 0. Headline finding: the monitor is itself a live performance problem

**Since the 2026.10.1 upgrade, every hourly health check blocks the HA event loop for about 65 seconds.**

How this was established. These are recorder reads only, and none of them is inferred from the code:

- `sensor.ha_health_monitor_last_health_check` is stamped at the end of each run. Normally consecutive stamps are 3600 s apart, because the coordinator schedules the next run after the previous one finishes. Before 2026-10-12 20:24 UTC, the drift past 3600 s was 0 to 5 s. From the 21:28 UTC run onward, every run drifts **+64 to +75 s**. One run, the first after the upgrade, drifted +245 s.
- `/config/.HA_VERSION` mtime is 2026-10-12 15:24:16 CDT, which is 20:24 UTC. That is the exact onset.
- Falsification check: the `states` table has **zero writes in the 60 s before each post-upgrade run's end stamp**, and about 3,600 writes in the 60 s before that. The largest write gap is 64.7 to 65.0 s, ending about 0.5 s before the stamp, at 21:28, 02:34 and 11:44. The control run before the upgrade (19:04) has a maximum gap of 4.8 s, and it is not adjacent to the run. A whole-process freeze of exactly that length that ends at the stamp means the loop was blocked by this coordinator.
- Likely mechanism: the code is synchronous with no `await` (`coordinator.py:59-74`). Three of its passes (`_analyze_zigbee_devices`, `_analyze_zwave_devices`, `_analyze_wifi_devices`) loop over **every state** (about 26k). For each one they do registry lookups and read `device_entry.config_entries`. That is the same deprecated `DeviceEntry.config_entries` access that made PadSpan expensive through HA's frame-walk deprecation reporting. Roughly 3 × (entities with a device) reads per run fits about 60 s at the per-call cost PadSpan showed. **Caveat:** I could not read HA core source (no docker access from the SSH add-on), so the deprecation is the operator's PadSpan finding applied here, not something I verified independently. The 65 s stall itself is measured.
- Consequence: a once-an-hour, 65 s full stall is long enough to trip the Supervisor watchdog ("missed Core API response") and to drop websockets. **It should be treated as a candidate contributor to the unexplained restarts.** Recommended operator action, and it is config only: disable the config entry now. I did not do this because the task is read-only.

Irony worth recording: the house's only "health monitor" caused the exact failure class the operator spent two days finding by hand.

---

## 1. Audit of what exists

### Files
`__init__.py` (59), `coordinator.py` (619), `sensor.py` (368), `button.py` (50), `config_flow.py` (95), `const.py` (54), strings and translations, `docs/` (README, CHANGELOG, DEVICE_LEVEL_TRACKING, plus an `Old/` copy), and `examples/` (5 dashboard and automation YAMLs, two of them `.yamlv1` leftovers). The manifest says `local_polling`, and the documentation and issue URLs point at a GitHub repo that does not exist. The CHANGELOG dates 1.3.0 to 2024-12-10, which is a typo for 2025.

### What it measures and how
One `DataUpdateCoordinator`. The default interval is 3600 s (the minimum is 900 s), and it is live at 3600. Each run does the following:

| Pass | Method | What it does |
|---|---|---|
| All devices | `_analyze_devices` | Iterates `hass.states.async_all()`. For each state that is `unavailable` or `unknown`, it looks up the entity and device registries and groups by device. |
| Matter | `_analyze_matter_devices` | Full state iteration. A state counts as "Matter" if `"matter"` or `"thread"` is a **substring of the entity_id** or of a non-standard `integration` attribute. This is a name heuristic and is wrong in both directions. |
| Zigbee / Z-Wave / Wi-Fi | `_analyze_*_devices` ×3 | Full state iteration. For **every** entity with a device (not only offline ones), it reads `device_entry.config_entries` and resolves each entry's domain. Wi-Fi also treats any device with a MAC connection as Wi-Fi, which captures Ethernet, BLE and almost everything else. |
| Logs | `_analyze_logs` | **A stub.** It returns empty categories (`coordinator.py:470-523`). The "Log Errors" sensor has always been 0. |
| Diff | `_track_*_offline_changes` | Compares the set of offline device IDs with the previous run, in memory only. A restart resets it, so after every restart all offline devices count as "newly offline". |

### Verdict derivation
`_calculate_health_status`: `critical` if more than 10 devices are offline or more than 3 Matter devices are; `warning` if more than 3 devices are offline, or any Matter device is, or there are more than 10 log errors (impossible, since logs are stubbed); otherwise `healthy`. Per-protocol `protocol_health` uses fixed counts (for example Zigbee critical above 5).

### Live values (2026-10-13 12:45 UTC)
`health_status = critical`, `offline_devices = 977`, `wifi_devices_offline = 334`, `matter_device_issues = 28`, `z_wave_devices_offline = 3` (this house has no Z-Wave network, so the number is a misclassification), `log_errors = 0`.
With 977 "offline devices" against a threshold of 10, **the headline is permanently critical, so it carries no information.** The count includes `unknown` (many sensors legitimately sit in `unknown`), disabled-device leftovers, and devices where one diagnostic entity is unavailable.

### Cost profile
| Dimension | Finding |
|---|---|
| Full-state iteration | Yes, 5 passes over about 26.7k states, all on the event loop. |
| Registry per poll | Yes, two registry lookups per state per pass, plus `config_entries` resolution. |
| Blocking IO | None (no file or network IO). The cost is pure CPU on the loop, which is what makes it hurt. |
| Event loop | **About 65 s of blocking per hour since 2026.10.1** (§0). |
| Recorder | Modest: about 770 KB of attributes over 2 days across 14 entities (each `health_status` row is about 2.8 KB). Attributes hold device-dict lists capped at 20. Not a meaningful DB cost. |
| Restart behaviour | `async_config_entry_first_refresh` runs the same expensive pass during startup, so it adds about 65 s to boot. |

### Noise versus signal
- **Noise:** the headline status (pinned critical), every "offline count" (unknown is treated as offline, entity-level noise rolls up to devices), the protocol classification (substring and MAC heuristics), "Log Errors" (a stub), "newly offline" after restart, and the 14 entities with "note" attributes.
- **Weak signal:** the *delta* sets (newly offline / came online) between runs. Hourly sampling still misses all flapping: a Sonoff relay that drops 300 times a day and is back by the top of the hour never appears.
- **Signal missed entirely:** every real failure from the last two days (§3).

---

## 2. The popular one: HAGHS (Home Assistant Global Health Score)

Repo: https://github.com/HA-Pulse/home-assistant-global-health-score (originally D-N91). Featured on How-To Geek, on HACS, and discussed on the HA community forums.

- **Score** = ⌊0.4 × Hardware + 0.6 × Application⌋, 0 to 100.
- **Hardware:** Linux PSI `/proc/pressure/{cpu,memory,io}` (or utilisation sensors as a fallback) and disk free, with tiered penalties.
- **Application:** "zombie" entities (unavailable or unknown past a 5 min grace, or 60 min for battery devices; ratio-scaled, up to 20 points), dead devices (informational), DB size above `1000 + 2.5 × entities` MB, pending updates and core age (up to 35 points), ConfigEntry `SETUP_ERROR` / `SETUP_RETRY` / `FAILED_UNLOAD` (5 points each, up to 15), open repairs (up to 10), stale backups (30), and a recorder-config bonus.
- **Cost:** the default update interval is **60 s**. Each run scans the entity registry and the state machine for zombies, and the attributes carry lists of up to 100 entities. In a house this size, that is a 26k-entity scan every minute plus large attribute rows recorded every minute. That is the most plausible way "a score integration hurt my system". The issue tracker shows one staleness bug (#103, stops updating) and no explicit CPU issues, so the operator's experience is not documented there.
- **Worth taking:** PSI as a cheap host-pressure signal; using the ConfigEntry state API rather than parsing logs; repairs count; grace windows; the "failed pillar → neutral" timeout.
- **Worth rejecting:** a single opaque 0–100 score (penalties mix "an update is pending" with "the loop is stalled"), full-state scans on a timer, and large list attributes. It has no event-loop latency signal, no flap rate and no silent-device detection, so **it would have caught none of the incidents in §3** apart from DB size.

---

## 3. Grounding: this house's real failures against what could have caught them

| Incident | Caught by HAHM? | By HAGHS? | Cheapest in-HA marker that would have caught it |
|---|---|---|---|
| Loop blocked 6–11 s every 13–15 s (PadSpan deprecation storm) | No | No (PSI might show CPU pressure, but without attribution) | **Loop-lag probe** + **deprecation-warning counter per integration** (log handler) |
| Mac app websocket drops about every 60 s | No | No | Follows from loop lag. Disconnect rate needs the `websocket_api` connection count (see §4, M8) |
| ~17 Sonoff relays unavailable 30–300 times/day (mDNS filtered → cloud fallback) | No (hourly snapshot misses flaps) | No (5 min grace hides flaps) | **Flap rate per integration/device** (state_changed listener, transitions to `unavailable`) |
| Matter node silent for 6 h, never unavailable; dead node retrying for 14 days | No | No | **Silent-device detection** (no state change for longer than its learned cadence) + **log rate per integration** (subscription timeouts) |
| Recorder DB 13.7 GB (now 14.7 GB on disk) | No | Yes (DB limit) | **DB size + growth/day + recorder queue backlog** |
| Unexplained restarts, watchdog "missed Core API response" | No | No | **Restart counter with uptime, and a reason for an unclean shutdown** (needs the previous run's marker) |
| Stuck shell loop polling the Supervisor API unauthenticated | No | No | Mostly **not measurable from inside Core** (it hits the Supervisor, not Core). Partial: `http.ban`/auth-failure log rate if it hits Core |
| WhatsApp regenerating QR PNGs on the loop (~0.7 s each) | No | No | **Loop-lag probe** + HA's own "Detected blocking call" warnings, counted per integration |
| Orphaned entity after a SPAN circuit ID change | No | Partially (zombie) | **Orphan detection**: registry entity with no state for more than N hours since startup, run once a day off the loop |

Four of the nine are fundamentally **loop health** problems. Two are **device liveness dynamics** (flapping and silence) rather than snapshots. None needed a score.

---

## 4. Recommended health model: markers, not a score

Principle: **every marker is event-driven or sampled cheaply, attributes are small, and each one surfaces as an actionable repair issue that names the culprit.** There is a small set of numeric sensors for trending, and no composite score. If a roll-up is wanted at all, use one `binary_sensor.ha_health_problem` that is on when any repair issue from this integration is open.

### Ranked markers

**M1. Event-loop lag (highest impact).**
- Measure: a `loop.call_later` heartbeat every 1 s that records `actual − expected` delay. Keep a 60 s ring buffer and publish p50/p99/max once a minute. Cost: one callback per second.
- Attribution: when lag exceeds 1 s, sample the loop thread's stack from a *separate* thread (`sys._current_frames()`) during the stall, and keep the top module path. This is cheap because it only runs while a stall is happening. That is what Profiler did by hand, automated and bounded.
- Thresholds: p99 > 250 ms for 5 minutes → warning repair. Any single stall > 5 s → repair naming the top frame's integration.
- Sensors: `loop_lag_p99_ms`, `loop_stalls_per_hour`.

**M2. Per-integration warning storms (deprecation and "blocking call").**
- Measure: a `logging.Handler` on the root logger that only counts records at WARNING and above, keyed by (logger-derived integration, message template). It does not format messages or store them beyond a 1-in-N sample. HA's frame helper logs the offending integration in the message, so key on that.
- Thresholds: more than 100 of the same template per hour from one integration → repair ("PadSpan: 7,700 deprecation reports/min").
- Caveat: HA deduplicates some of `report_usage`, so the log count understates the call count. Loop lag (M1) catches the cost even when the log line is deduplicated.

**M3. Config entry state and retry loops.**
- Measure: listen for config entry state changes (the `async_on_state_change` / entry listener API; verify the exact hook against current HA source before building). Count transitions into `SETUP_RETRY` and `SETUP_ERROR` per entry per day.
- Thresholds: an entry in `SETUP_RETRY` for more than 30 minutes, or more than 20 retries a day → repair.

**M4. Flap rate per integration and device.**
- Measure: one `EVENT_STATE_CHANGED` listener that does an O(1) dict increment only when `new_state.state == "unavailable"` and the old state was not. Resolve entity → device → integration lazily, and cache it, only for flapping entities. Roll up hourly.
- Thresholds: a device with more than 10 unavailable transitions a day → repair. More than 5 devices of the same integration flapping together → integration-level repair ("sonoff: 17 devices, 1,900 drops/day, likely network/mDNS").
- Output: `flapping_devices` count. The attribute is the top 10 only.

**M5. Silent devices.**
- Measure: in the same listener, keep `last_change_ts` per device (a dict write). Once an hour, in an executor or in chunks, compare against a learned typical interval (an EWMA of inter-change gaps). Only devices with at least N observed changes qualify; static entities are excluded.
- Threshold: silent for more than 6× the typical interval and more than 1 h → repair. Restrict by default to integrations with push semantics (matter, zha, mqtt, esphome).
- Honest limit: this cannot distinguish "dead" from "nothing happened" for event-only sensors. Make it opt-in per integration.

**M6. Recorder health.**
- DB file size (`os.stat` in an executor) and growth per day from a daily snapshot. Recorder queue length (`recorder` instance `backlog`), sampled once a minute.
- Thresholds: queue > 1,000 → warning, > 10,000 → critical. Growth > 200 MB/day or size > 2× a configured target → repair that lists the top 10 entities by row count. That query is expensive, so it runs **only when the operator presses a button**, read-only, in an executor.

**M7. Restarts and unclean shutdowns.**
- On startup, write a marker to `.storage`; on a clean `EVENT_HOMEASSISTANT_STOP`, clear it. If the marker is still there at startup, the previous run ended uncleanly. Count restarts over 7 days.
- Thresholds: more than 1 unclean restart in 7 days → repair. Correlate with the M1 history saved before the crash.
- Limit: the watchdog's reason lives in the Supervisor log. A best-effort Supervisor API read (`/core/logs` or `/supervisor/logs`) is possible on HA OS only.

**M8. Websocket disconnect rate.**
- Honest limit: Core exposes no public disconnect event. Polling the active connection count (`hass.data` websocket connection sensor from the `websocket_api` integration) once a minute and counting decreases approximates it. Often it is a symptom of M1 rather than a separate cause, so rank it low.

**M9. Orphaned and stale registry entries.**
- Once a day, in chunks with `await asyncio.sleep(0)` between batches: registry entities with no state for more than 24 h since startup, and devices with no entities. This produces a repair with a list and **never deletes anything**.

**Not measured, deliberately:** host CPU/RAM (use `systemmonitor`, which is already installed, or PSI as a single cheap sensor), pending updates (HA already has update entities), and backups (HA has its own repair).

### What to drop from v1.3.0
All of it, as a design. Specifically:
- every full-state, multi-pass scan on the loop (the cause of the 65 s stall);
- protocol classification by substring or MAC (wrong, and adds cost);
- `unknown` treated as offline;
- the threshold-based "critical/warning/healthy" headline;
- the log stub sensor;
- the "note" attributes and 20-item device-dict attributes;
- the `.yamlv1` example clutter.

Keep only the idea of *transition* tracking (newly offline / came online), redone as event-driven flapping (M4).

---

## 5. Packaging
- A new repo (`ha-health-monitor` v2, a clean domain or a major-version migration that removes the old entities), pushed to GitHub and homelab Gitea.
- HACS-ready: `hacs.json`, `manifest.json` with a real repo URL, `iot_class: calculated`, brand assets.
- Tests with `pytest-homeassistant-custom-component`. A **performance test** is mandatory: with 30k synthetic entities, the `state_changed` handler stays under 20 µs mean and no scheduled job holds the loop for more than 10 ms (asserted with a lag probe inside the test).
- CI: hassfest + HACS action + pytest.
- Diagnostics download (`diagnostics.py`) for the ring buffers.

## 6. Phased plan (smallest valuable first)
1. **Phase 0, now, config only:** disable the current `ha_health_monitor` entry (§0). Removes about 65 s of loop stall per hour.
2. **Phase 1:** M1 loop lag with stall attribution + M3 config entry retry. This alone would have caught PadSpan and WhatsApp.
3. **Phase 2:** M2 warning-storm counter + M7 restart tracking.
4. **Phase 3:** M4 flap rate + M6 recorder size, growth and backlog. Catches the Sonoff event and the 14.7 GB DB.
5. **Phase 4:** M5 silent devices (opt-in), M9 orphans, M8 websocket approximation.
6. **Phase 5 (optional):** the problem binary sensor, a dashboard card and a HACS release.

## 7. Performance guardrails (the monitor must never become the problem)
1. **No full-state or full-registry iteration on the event loop, ever.** Daily sweeps run in chunks of 500 or fewer with `await asyncio.sleep(0)` between them, or in an executor over a snapshot copy.
2. **Hot-path budget:** the `state_changed` handler does a constant-time dict update and nothing else. No registry lookups on the hot path; resolution is lazy and cached.
3. **Self-measurement:** the monitor times its own callbacks and jobs. If any exceeds 50 ms, it logs once, raises a repair against itself, and backs off (doubles its interval).
4. **Bounded memory:** every map is LRU-capped (for example 5,000 devices) and ring buffers are fixed size.
5. **Recorder hygiene:** at most about 10 numeric sensors. List attributes are capped at 10 short strings, and large ones are excluded from the recorder (`_unrecorded_attributes`). Details go in repairs and diagnostics, not in state history.
6. **No deprecated APIs:** CI runs with deprecation warnings set to raise.
7. **Kill switch:** each marker can be turned off in the options flow, and the entry unloads cleanly (all listeners removed, test-verified).
8. **Expensive queries only on a button press** (DB top-N), read-only, in an executor, with a timeout.

## Sources
- [HAGHS repo](https://github.com/HA-Pulse/home-assistant-global-health-score), [issues](https://github.com/HA-Pulse/home-assistant-global-health-score/issues)
- [HAGHS community thread](https://community.home-assistant.io/t/haghs-global-health-score-is-your-instance-truly-healthy-featured-on-how-to-geek/985573)
- [H.A.C.A. config auditor](https://github.com/JeanMarc-Labs/ha-config-auditor) (adjacent; not evaluated in depth)
