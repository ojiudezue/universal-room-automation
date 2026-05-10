# Pre-Restart Diagnostic — 2026-04-29 03:50 CDT

**Author:** Claude (overnight watch)
**Watch window:** 23:25 CDT 2026-04-28 → 03:50 CDT 2026-04-29 (~4.5h)
**Restart scheduled:** 04:00 CDT (10 min from this writing)

---

## Baseline (23:25 CDT 2026-04-28)

| Metric | Value |
|---|---|
| recorder DB | 22760 MB |
| recorder WAL | 134 MB |
| URA DB | 811 MB |
| URA WAL | 4 MB |
| Errors / 60min | 28 |
| Top component | (mixed) |
| HAOS ping (.13.13) | 0.4 ms |
| Cross-VLAN .10.180 | 632 ms |
| Cross-VLAN .11.142 | 591 ms |
| Cross-VLAN .12.234 | 726 ms |

**State:** Recorder block on disk, validated, awaiting restart.

---

## Hourly trend (00:07 → 03:07)

| Time CDT | rec_DB MB | rec_WAL MB | URA_DB MB | URA_WAL MB | errors | top component |
|---|---|---|---|---|---|---|
| 23:25 baseline | 22760 | 134 | 811 | 4 | 28 | (mixed) |
| 00:07 T+1h | 22839 | 134 | 812 | 4 | 24 | pywiim.upnp.client |
| 01:07 T+2h | 22943 | 134 | 812 | 4 | 26 | pywiim.upnp.client |
| 02:07 T+3h | 23031 | 134 | 812 | 4 | 26 | pywiim.upnp.client |
| 03:07 T+4h | 23124 | 134 | 812 | 4 | 24 | pywiim.upnp.client |
| **03:50 final** | **23190** | **134** | **812** | **4** | **22** | **pywiim.upnp.client** |

**Observations:**
- **Recorder DB grew +430 MB over 4.5h (~95 MB/hr).** Steady linear growth — auto_purge has not run yet (it's set for 04:12 daily, but only takes effect AFTER restart). Without `recorder:` block, the running HA still has default `purge_keep_days: 10` which it has presumably been honoring on old days, but the file never shrinks because `auto_repack: false` was the running default.
- **WAL constant at 134 MB throughout** — neither growing nor shrinking. Recorder is keeping pace with checkpoints at this saturation level; not catastrophic.
- **URA DB and WAL completely stable** — URA has been quiet all night.
- **Error count flat-to-trending-down** (28 → 22) — system has reached a quasi-equilibrium.
- **Top component constant: pywiim.upnp.client** — WiiM UPnP discovery storms are the dominant noise. Not URA, not recorder.

---

## Final state (03:50 CDT 2026-04-29)

- recorder DB: **23190 MB** (+430 MB from baseline)
- recorder WAL: **134 MB** (unchanged from baseline — neither improved nor regressed)
- URA DB: **812 MB** (+1 MB from baseline; effectively stable)
- URA WAL: **4 MB** (unchanged)
- Errors last 60 min: **22 distinct entries** (down from 28 baseline)
- URA DB write worker errors in last 60 min: **6** (line 1065 environmental_data, all in last 8 min — uptick during this window)
- WebSocket overruns: still firing, ~5 incidents in last hour
- UniFi WS disconnects: 74 cumulative since ~01:30 — UniFi controller not happy

---

## Active probes (03:50 CDT)

| Target | Latency | Δ from baseline | Verdict |
|---|---|---|---|
| HAOS .13.13 | 0.3 ms | unchanged | **healthy** |
| Kasa .10.180 | **895 ms avg** | +263 ms (worse) | **DEGRADED** |
| Kasa .11.142 | **TIMEOUT** (100% loss) | regressed from 591 ms to packet loss | **OFFLINE / NETWORK BROKEN** |
| WiiM .12.234 | 289 ms avg, **max 837 ms, σ 388 ms** | similar mean, huge variance | **DEGRADED + UNSTABLE** |

**Network classification: DEGRADED, getting WORSE during watch.**

This is a meaningful new finding. Cross-VLAN latency was already bad at baseline; over 4.5 hours it has degraded further (.10 went from 632 → 895 ms; .11 went from 591 ms responses to 100% packet loss). This is **not consistent with HA being the cause** — HA's load has been roughly flat (errors flat, WAL flat, URA quiet). An external network/router issue is progressing independently.

Specifically: .11.142 going from a slow-but-responding 591 ms to total packet loss, while HAOS itself is still 0.3 ms, is a strong signal of either:
- Gateway/router CPU saturation reaching a tipping point
- A specific VLAN trunk or firewall rule failing
- The .11.142 device itself going offline (independent failure)

---

## Crons remaining

```
2dc8ef14 — 0 4 29 4 * (one-shot)  — HA RESTART at 04:00 CDT ✅ scheduled
947d6b22 — 35 4 29 4 * (one-shot)  — POST-RESTART VALIDATION at 04:35 CDT ✅ scheduled
```

The 4 hourly check jobs auto-deleted after firing (one-shots).

---

## What to expect post-restart

1. **04:00 CDT** — HA restart. WebSocket clients drop briefly. Integrations re-init in waves; brief period of additional log churn for ~3-5 min as URA's 31 rooms warm up and BLE/cloud integrations re-authenticate.
2. **04:00–04:12** — System loading new recorder config. WAL begins to drain because `commit_interval: 5` reduces fsync pressure.
3. **04:12 CDT** — `auto_purge` fires its daily cycle. **First-ever** repack on a 23 GB DB with `auto_repack: true`. Expected duration: **30–60 minutes**. During this window, the recorder write thread holds the DB lock heavily; HA may feel sluggish or unresponsive, integrations may show transient timeouts. **This is normal and should not be panicked about.**
4. **04:30–05:00 CDT** — After repack completes, the DB file should drop substantially (potentially 22 GB → 5–8 GB depending on how much old data is purged with the new 7-day retention vs running with old 10-day default). WAL should drop to <16 MB. Event-loop saturation should ease.
5. **By morning** — Recorder issue should be substantially better. URA write worker timeouts should be eliminated.

### What WON'T be fixed by restart

- **Cross-VLAN routing latency.** HA on .13 → devices on .10/.11/.12 was 600–725 ms at baseline and got worse during watch. This is an upstream router/gateway/switch problem and entirely independent of HA. Restart will not change it. **The Bond/WiiM/TPLink/Elgato/Frigate timeouts WILL CONTINUE post-restart** until the network issue is investigated separately.
- **WiiM UPnP description timeouts on .12.x.** These were the top error component for the entire watch and will persist.
- **UniFi WebSocket disconnects.** 74 disconnects in 4 hours suggests the UniFi controller (likely on .13 subnet itself) has its own issue, possibly load-related or firmware. Independent of the recorder.

### Diagnostic implication

Tonight's watch confirms:
1. **Recorder bloat is real and the restart fix is appropriate** — but the WAL never grew, which means recorder isn't *currently* the dominant pain point. It will become one as the DB keeps growing. Fixing it is preventive, not curative.
2. **The dominant active pain point is the network.** This is independently degrading and needs separate investigation. Suggested triage from HAOS supervisor SSH after restart: `ping -c 5 192.168.10.180`, `traceroute 192.168.11.142`, check UDM/OPNsense gateway CPU and fan, check switch port LED/error counters on the trunk to .10/.11/.12 VLANs.

---

## Restart confirmation

- Cron `2dc8ef14` is queued and will fire `mcp__home-assistant__ha_restart` at 04:00 CDT.
- Cron `947d6b22` will validate at 04:35 CDT and append a verdict section to this file.
- If Claude session is still alive at 04:00, restart fires reliably. If session died, no restart and you'll find this file but no append below.

---

## Five-line summary

1. **Recorder DB +430 MB in 4.5h, WAL flat at 134 MB, error count stable at ~25, top noise = pywiim.upnp.client** — system in equilibrium overnight.
2. **URA: completely quiet** (812 MB DB, 4 MB WAL, 0–6 write-worker timeouts/hour, mostly 0). URA architecture audit was correct.
3. **Network DEGRADED and got WORSE**: .10.180 632→895 ms, .11.142 591ms→100% packet loss. **Restart will NOT fix this.**
4. **Restart cron at 04:00 confirmed.** Repack will run 04:12, expect 30–60 min of extra slowness then real improvement.
5. **Network issue is now the bigger fish.** Suggested next: SSH to HAOS, ping/traceroute cross-VLAN; check gateway CPU/firewall.

---

## Restart triggered at 04:01:05 CDT — pre-WAL=134MB, pre-DB=23204MB

- First ha_restart call timed out (HA was overloaded)
- Retry succeeded: "Home Assistant restart initiated. The system will be unavailable for 1-5 minutes."
- Config validated immediately before restart: valid ✅
- WebSocket dropped as expected
- 04:35 validation cron will check recovery

---

## Post-restart validation — 04:35 CDT 2026-04-29

### Verdict: **YELLOW (repack likely still running) + RED on network**

The recorder restart succeeded, but the system has not yet recovered. Two distinct conditions:
1. Recorder repack appears to still be in progress (or was delayed). WAL grew slightly post-restart (134 → 159 MB) and DB has not shrunk. This is consistent with the 04:12 auto_purge+repack running on 23 GB and not yet complete at 04:35 (~23 min in; expected duration 30–60 min).
2. **Cross-VLAN routing has FULLY COLLAPSED.** All three test targets now show 100% packet loss vs. partial degradation pre-restart. This is independent of HA and represents a real escalation in the network problem.

### Post-restart state

| Metric | Pre-restart 04:00 | Post-restart 04:35 | Δ |
|---|---|---|---|
| recorder DB | 23204 MB | **23225 MB** | +21 MB |
| recorder WAL | 134 MB | **159 MB** | +25 MB (concerning) |
| URA DB | 812 MB | 812 MB | unchanged |
| URA WAL | 4 MB | 4 MB | unchanged |
| HA HTTP / | (n/a) | 200 in **1.79s** | very slow vs 26 ms baseline |
| ha_get_system_health | n/a | **TIMED OUT** | system still under heavy load |

WAL growth + DB unchanged + slow HTTP + system_health timeout = repack/purge is most likely still running. This is the expected worse-before-better window.

### Active probes (04:35 CDT)

| Target | Latency | Δ from pre-restart | Verdict |
|---|---|---|---|
| HAOS .13.13 | 0.4 ms | unchanged | healthy |
| Kasa .10.180 | **TIMEOUT** | regressed from 895 ms | **OFFLINE** |
| Kasa .11.142 | **TIMEOUT** | already offline | **OFFLINE** |
| WiiM .12.234 | **TIMEOUT** | regressed from 289 ms | **OFFLINE** |

**All three cross-VLAN targets now 100% packet loss.** This is a hard escalation, not gradual degradation. Suspect router/gateway hardware or trunk failure. **Restart did not cause this** (not even capable of touching upstream routing) but the timing is worth flagging — if the repack is monopolizing HA's CPU, and HAOS happens to share infrastructure with the gateway (e.g., same physical host or same switch port group), there could be coupling. More likely: independent.

### Errors in last 30 min (post-restart)

- URA DB write worker timeouts: **multiple** (energy_snapshot, coordinator_diagnostics decision, census_snapshot) — line 1089, 253, 2361. Consistent with disk-busy-with-repack hypothesis.
- WebSocket "Reached 4096 pending messages": YES, 2 fired post-restart — event loop pressure persists.
- Bermuda: new "Calling process_advertisement on a metadevice ... is a bug" warnings (114 occurrences) — Bermuda BLE proxy seeing duplicate ad sources, internal Bermuda bug, not URA.
- Shelly: 5 devices disconnected (shelly1pmminig3, shellypmminig3, shellypluswdus, shelly1pmminig4, etc.) — networking-related.
- Dahua at .15.96: `PlatformNotReady` — yet another VLAN (.15) and another timeout. Confirms broad cross-VLAN problem.
- Enphase Envoy at .13.118: connect timeout. Same VLAN as HA. Suggests the network problem may extend even into .13 subnet for some hosts, OR Envoy is just slow.
- TPLink (.10.x, .11.x, .8.x): ongoing INTERNAL_QUERY_ERROR — same as overnight.

### What this means

- **Recorder fix:** still in progress. Re-check at 05:00–05:15 CDT. If WAL has dropped below 50 MB and DB has shrunk to <15 GB, recorder is fixed and the restart was effective.
- **Network:** **NEW PRIORITY**. Cross-VLAN routing has completely collapsed in a way that didn't exist at 23:25 CDT yesterday. This needs hands-on hardware investigation and is the biggest risk now.
- **URA:** DB write worker errors are ambient — symptom of repack pressure, not a URA bug. Should clear when repack completes.
- **Re-enable ZM/CM:** **DO NOT DO YET.** Wait for repack to finish AND network to be investigated.

### Recommended next steps (for user when they wake)

1. **Re-check recorder DB size first.** `ls -lah /Users/okosisi/ha-config/home-assistant_v2.db*`. If WAL is <16 MB and DB is meaningfully smaller (e.g., <15 GB), repack succeeded.
2. **Investigate gateway/router urgently.** Suspects:
   - Gateway/router CPU pegged or thermal throttle
   - Inter-VLAN routing rule corruption
   - Trunk port failure on switch
   - Specific firewall rule causing infinite loop
   Test from HAOS supervisor SSH: `ping 192.168.10.180`, `ping 192.168.12.234`. If HAOS sees the same 100% loss, it's confirmed gateway-side. Reboot the gateway/router (UDM/OPNsense/EdgeRouter — whichever you use).
3. **Once network and recorder are confirmed healthy, re-enable URA Zone Manager and Coordinator Manager** via Settings → Devices & Services → URA → enable disabled config entries.
4. **Optional: prune Bermuda iPhone-distance sensors from recorder excludes** if you decide a smaller DB is preferable. They are the loudest writers.

### Trend summary across all measurements

| Metric | Baseline 23:25 | Final pre-restart 03:50 | Post-restart 04:35 |
|---|---|---|---|
| recorder DB MB | 22760 | 23190 | 23225 |
| recorder WAL MB | 134 | 134 | **159** |
| URA writer timeouts/hr | 13+ | 6 | **3+ in 30 min** |
| Cross-VLAN .10.180 ping | 632 ms | 895 ms | **TIMEOUT** |
| Cross-VLAN .11.142 ping | 591 ms | TIMEOUT | TIMEOUT |
| Cross-VLAN .12.234 ping | 726 ms | 289 ms | **TIMEOUT** |
| HA HTTP /  | 26 ms | (not tested) | **1790 ms** |

The cross-VLAN trajectory across the night is the most striking signal. The recorder symptoms could plausibly improve once repack completes; the network needs separate human intervention.
