# INVESTIGATION — HA Health Monitor `loop_stall:universal_room_automation` (hvac_override)

**Date:** 2026-10-13 · **Deployed:** v5.103.55 (develop `5ecadb523`) · **HA:** 2026.10.1, Python 3.14.6
**Mode:** read-only. No URA code changed, no restart. One `profiler.start` (330 s) run.
**Read first:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (complete), `docs/QUALITY_CONTEXT.md`.

## 1. Verdict (short)

- **URA really does cause a stall on its 5-minute HVAC tick.** The stall happens about 3–6 s after each decision cycle, inside `OverrideArrester._refresh_a1_cache` → `_high_draw_time_s_7d` (`domain_coordinators/hvac_override.py:1779-1846`). The A1 diagnostic refresh is called at `hvac_override.py:5163`, at the end of every cycle.
- **URA is not the main source of the house's stall load.** In the same hour the loop paused for about 1.7–2.0 s roughly every 80 s (50 stalls/h). Those pauses landed on unrelated sites: ssl, selectors, weakref, sqlalchemy, paho, unifi, wiim and bermuda. Only the tick-aligned stalls belong to URA, about 11 of 50.
- **The blocking statement is not expensive work.** The sampled lines are trivial bytecode:
  - `:1833` is `ts = getattr(st, "last_updated", …)`.
  - `:1841` is `total_high_s += (ts_local - prev_ts).total_seconds()`.

  When the loop sits on such lines for 2 s, the thread is paused, not computing. **Leading hypothesis (UNVERIFIED):** the allocation burst of this loop triggers a stop-the-world full (gen-2) cyclic GC over HA's large heap. A GIL hold by another thread is the alternative. The same mechanism would explain the house-wide ~80 s pauses at random sites. URA's tick allocates heavily at a fixed time, so it reliably "catches" one.

## 2. Evidence

### 2.1 Health-monitor samples (diagnostics of entry `01KC3NJZHQHF5GHKY46MM2P40A`)

| at (UTC) | dur | site |
|---|---|---|
| 17:53:55 | 2.193 s | `hvac_override.py:1833 (_high_draw_time_s_7d)` |
| 17:58:54 | 2.059 s | `hvac_override.py:1841 (_high_draw_time_s_7d)` |
| 18:58:54 | 2.196 s | `hvac_override.py:1833 (_high_draw_time_s_7d)`, **2 samples** (≥ 0.7 s inside the loop) |

Other tick-aligned stalls carry generic sites, for example `18:03:54 ssl.py`, `18:23:55 selectors.py`, `18:28:55 ssl.py`, `18:33:54 wiim`, `18:38:54 selector_events`, `18:43:56 selectors.py` and `18:48:54 selectors.py`.

### 2.2 Cadence match

- HVAC `decision_log` rows land at `:X3:48.98` / `:X8:48.98` UTC every 5 min. Writes follow at `:51.8`. Source: URA DB `decision_log` and `ura_activity_log`. Constant `HVAC_DECISION_TICK` = 5 min (state of play §2).
- A stall is recorded at tick + 5–6 s on **11 of the 12 ticks** between 17:53 and 18:58 UTC. The 18:53 tick had none.
- The expected rate by chance is about 1: a 6 s window per 300 s × 50 stalls/h.
- The tick-aligned stalls are slightly longer (median 2.1 s vs about 1.85 s for the rest).

### 2.3 Profiler (`/config/profile.1791917478276820.cprof`, 331 s, 13:51:20–13:56:50 CDT)

- `_high_draw_time_s_7d`: 6 calls (2 ticks × 3 zones), cumtime **0.265 s** (about 44 ms/call). It made 27,981 `as_local` calls, so about 4.7k significant states per zone per call.
- This window covered the **18:53 tick, the one tick with no stall**. So 44 ms is the cost when no pause hits. The work itself is cheap; the 2 s is a pause.
- The other URA hot frames in this profile are not tick-related and none blocks for long:
  - `coordinator.py:3046 _get_entities_in_area`: 3,348 calls, 2.49 s total (0.74 ms/call).
  - `sensor.py:15178 async_update`: 2.5 s over 340 calls.
- The profile records only the loop thread. Executor work (`get_significant_states` in the recorder executor) and GC time are invisible to it.

### 2.4 Data volume

- Recorder rows over 7 days: `sensor.span_panel_ac1_power` 92,150; `sensor.span_panel_ac_2_power` 90,324; `sensor.span_panel_ac_3_power` 89,645.
- After significance filtering, about 4.7k states per zone are returned.
- Every 5 minutes URA asks the recorder to scan about 272k rows and build about 14k `State` objects. Each `.attributes` read is decoded lazily, and each row also allocates `datetime` objects.
- The result is a 7-day diagnostic, `gate4_high_draw_time_s_7d` (`sensor.py:18555`, display only). It cannot change meaningfully in 5 minutes.

## 3. Producer / consumer

- **Producer:** `_high_draw_time_s_7d` (`hvac_override.py:1779`). It calls `get_significant_states` in the recorder executor (`:1802-1805`), then iterates over every state **on the event loop** (`:1812-1843`).
  - Docstring claim: "Bounded once per 5-min cache refresh per zone … a few thousand rows". That holds after filtering, but the scan behind it is about 90k rows per zone.
- **Consumer:** `_a1_zone_cache[zone]["gate4_high_draw_time_s_7d"]`, which feeds the A1 diagnostic sensor (`sensor.py:18555`). It is display only; no decision reads it.
- **Sibling with the same pattern:** `hvac_override.py:6408-6440`, the nudge-eval `get_significant_states` over the restore → eval window. It covers a minutes-long window, so it is cheap; it is not a stall source today.

## 4. Bug classes (QUALITY_CONTEXT.md)

- **#26-family (sensor reads served from a cache)** is respected; the cache refresh itself is the problem.
- The closest matches are the **unbounded-loop-blocking family** (#25 unbounded DB work, and the cleanup-blocks-the-loop class at QUALITY_CONTEXT.md:1312-1343): per-tick work that scales with history and not with change.
- **Proposed new class:** "Per-tick recomputation of a long-window aggregate." A 7-day value is recomputed from raw history every 5 min, so its cost scales with window × sample rate even though the answer moves slowly. Fix by caching on the window's natural cadence, or by computing incrementally or from long-term statistics.

## 5. Recommended fix (Tier 1 hotfix; display-only consumer, no decision path)

1. **Refresh `_high_draw_time_s_7d` hourly, not every tick** (it carries the bulk of the gain):
   - Keep a per-zone `(value, computed_at)` and recompute only when it is older than a named constant, `HVAC_A1_HIGH_DRAW_REFRESH_S = 3600`. That is rung 1, a module const: it is a diagnostic cost bound, not a policy knob.
   - Effect: 12× fewer recorder scans and allocation bursts.
2. **Read long-term statistics, not states.** Call `recorder.statistics.statistics_during_period(..., period="5minute" or "hour", types={"mean"})` for the AC load sensor. The SPAN power sensors have `state_class: measurement`, but I have not verified that they have LTS rows; that needs confirming.
   - Load: 2,016 five-minute rows or 168 hourly rows instead of a ~90k-row scan.
   - Accuracy: high-draw time becomes "bucket mean ≥ threshold", which is coarser. That is acceptable for a display-only metric; note it in the sensor attrs.
3. **Move the iteration off the loop.** Do the parse/sum inside the executor callable, returning a float, so the loop never walks thousands of `State` objects.
   - This removes on-loop allocation but **not** a stop-the-world GC pause. That is why 1 and 2 matter more.
4. **Discriminating check before and after.** Count the health monitor's tick-aligned stalls (`at` within tick + 2..8 s) over 1 h.
   - Expected under the fix: about 1 (chance), down from about 11.
   - If the tick-aligned stalls stay at about 11 with the A1 high-draw path disabled, the hypothesis is wrong and the cause is elsewhere in the tick: `_refresh_impact_cache` at `:1990` or the other A1 SQL.

Tests: a unit test that a second refresh within the TTL issues no recorder call. Also a wire-in anchor that `_refresh_a1_cache` routes through the cache (call-neuter drill).

## 6. House-wide pauses (not URA; separate card)

- About 50 stalls of 1.7–2.0 s per hour at random sites, at a regular ~80–87 s cadence, is a process-level pause, not one integration.
- Candidate: a full cyclic GC over a large heap. Note: 566 tracked entries, 86 hot, and large paho/bermuda/unifi churn in the profile (paho `topic_matches_sub` 1.56 M calls, bermuda `calculate_data` 2.18 M).
- Whether Python 3.14's collector here is incremental or full is unknown (I'd be guessing).
- Discriminator: register a `gc.callbacks` timer, for example from a throwaway pyscript/custom component, and correlate collections ≥ 1 s with stall `at` times.
- The health monitor's per-integration attribution is misleading for this class. It blames whoever holds the loop when the pause hits.

## 7. Deprecated device-registry API sites (inventory; deprecation itself UNVERIFIED)

I could not read HA 2026.10's `helpers/device_registry.py`: the core container is not reachable from the ssh add-on, because the docker socket access was denied. The system log shows **no** deprecation warning from URA, and every stall sample has `deprecation: false`. So the "2026.10 deprecation + frame walk per call" claim is **unverified** here. Sites, for whoever verifies it:

| Site | API | Runs |
|---|---|---|
| `entity.py:80` | `async_get_device(identifiers=…)` | **per entity add** (every room entity at boot and on reload). The highest count by far, and a boot-time cost if the frame walk is real |
| `__init__.py:1404, 1410, 1441` | `async_get_device` | setup, once per entry/zone |
| `__init__.py:5305` | `async_get_device` | setup HVAC device migration |
| `__init__.py:5227` | iterates `dev_reg2.devices.values()` | setup, once |
| `config_flow.py:10742, 11934` | `async_get_device` | flow steps (user action) |
| `button.py:302-303` | `devices.values()` + `device.config_entries` | diagnostics button press |
| `_devices.py:267, 345, 438, 607` | `devices.values()` (+ `config_entries` set compare per `:228`) | setup / defrag |

The earlier-cited `__init__.py:4888/4966` have moved to `:5227` / `:5305` on v5.103.55. None of these runs on the 5-min tick, so none explains the steady-state stall. Boot had 18 stalls (`boot_stalls`); `entity.py:80` is the candidate to measure there. Recommendation: once the deprecation is confirmed against HA source, replace the calls with the non-deprecated lookup in one Tier-1 sweep, starting with `entity.py:80`. Read `docs/architecture/DEVICE_TREE.md` first.

## 8. Not done

- No thread-frame capture during a tick stall: I could not time `profiler.log_thread_frames` precisely enough. So "GC vs GIL" is still a hypothesis; §5.4 is the discriminator.
- HA source not read, so the deprecation status is unverified (§7).
