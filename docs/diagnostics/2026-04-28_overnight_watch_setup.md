# Overnight Recorder Watch — Setup Record

**Time set up:** 2026-04-28 23:25 CDT
**Author:** Claude (this session)
**Goal:** Restart HA at 04:00 CDT 2026-04-29 to activate new recorder config; monitor before/after.

---

## Current state at setup

- **Recorder DB:** 22.7 GB (`home-assistant_v2.db`)
- **Recorder WAL:** 134 MB (`home-assistant_v2.db-wal`) — far above healthy <16 MB
- **URA DB:** 811 MB (`universal_room_automation.db`)
- **URA WAL:** 4 MB — healthy
- **Active LAN probes from Mac (.13.163):**
  - HAOS host (.13.13): 0.4 ms ping, HTTP 200 in 26 ms — healthy
  - smlight (.13.119, same subnet): 2.7 ms — healthy
  - Frigate (.13.18, same subnet): timeout — unhealthy device
  - Cross-VLAN devices (.10/.11/.12): **600–725 ms ping** — degraded
  - DNS `homeassistant.local`: NXDOMAIN — mDNS not resolving
- **HA log signature:** integrations on .10/.11/.12 subnets all timing out (Bond, WiiM, TPLink, Elgato, Carrier, Frigate); URA DB write worker timing out at 35s on every writer path (`occupancy`, `environmental`, `energy`, `decision`, `person`, `room_state`); WebSocket clients hitting 4096 pending msg buffer.

---

## What was changed before this watch

**File:** `/Users/okosisi/ha-config/configuration.yaml`
**Backup:** `configuration.yaml.bak.2026-04-28-pre-recorder`

Added (will activate on next restart):
```yaml
recorder:
  purge_keep_days: 7
  commit_interval: 5
  auto_purge: true
  auto_repack: true
```

Validated via `mcp__home-assistant__ha_check_config` → "Configuration is valid".

---

## Hypothesis

Two co-equal problems:

1. **HA recorder bloat** (22 GB / 134 MB WAL with no `recorder:` block in config = pure defaults). Causes intermittent event-loop pauses during WAL checkpoints. The new config + restart should start shrinking the file via `auto_repack` at 04:12 daily auto-purge.
2. **Cross-VLAN routing degraded.** .13 → .10/.11/.12 latency is 600–725 ms vs. <3 ms same-subnet. **Restart will NOT fix this.** Likely router/gateway/firewall/trunk issue that needs separate investigation. May be an OPNsense/UDM/EdgeRouter issue; could also be a switch port problem.

URA's own DB and write architecture were audited (see Explore agent report in chat) and judged clean. URA is a passenger getting hit by recorder traffic on the shared HAOS disk, not a contributor at this scale.

---

## Schedule for the night

All Claude-side cron jobs — **session-only**, will not survive Claude Code closing or Mac sleeping.

| Time CDT | Cron ID | Action |
|---|---|---|
| 00:07 Apr 29 | `ecc0e1c9` | Hourly check 1 — append to `/tmp/ha_recorder_watch.csv` |
| 01:07 | `edd590fc` | Hourly check 2 |
| 02:07 | `5323ac6a` | Hourly check 3 |
| 03:07 | `2abf8eb7` | Hourly check 4 |
| 03:50 | `03ce8a24` | Final diagnostic — write `2026-04-29_pre_restart.md` |
| **04:00** | `2dc8ef14` | **`ha_restart`** |
| 04:35 | `947d6b22` | Post-restart validation, append verdict |

Trend CSV: `/tmp/ha_recorder_watch.csv`. Final diagnostic: `docs/diagnostics/2026-04-29_pre_restart.md`.

---

## Recovery if Claude session dies

If you wake up and HA was NOT restarted at 04:00:
1. The new recorder config is still safe on disk — just not active.
2. Restart HA manually (any time) via Settings → System → Restart, or `mcp__home-assistant__ha_restart` from a fresh Claude session.
3. After restart, watch for `home-assistant_v2.db-wal` to drop and `.db` to shrink (auto_purge at next 04:12). Repack on a 22 GB DB takes 30–60 min and worsens responsiveness while running.

If you want to revert the recorder config:
```bash
cp /Users/okosisi/ha-config/configuration.yaml.bak.2026-04-28-pre-recorder \
   /Users/okosisi/ha-config/configuration.yaml
```

---

## NIC topology (clarified after setup)

HAOS uses a **single physical NIC with multiple IPs** (not two NICs). Adapter list:
- `enp4s0 (192.168.13.13/24)` — primary, untagged
- `enp4s0.3 (192.168.8.13/22)` — VLAN ID 3, tagged sub-interface

Trunk-on-a-stick is a clean, recommended HAOS setup. **The NIC is not the bottleneck.** Cross-VLAN traffic (HA on .13 → devices on .10/.11/.12) traverses the upstream gateway/router for inter-VLAN routing — HA's NIC is not on that path. The 600–725 ms cross-VLAN latency observed from the Mac (also on .13) is upstream of HA.

## What to investigate next regardless of restart outcome

1. **Cross-VLAN latency** — independent of recorder. Test from HAOS supervisor SSH:
   ```bash
   ping -c 5 192.168.10.180
   ping -c 5 192.168.11.142
   ping -c 5 192.168.12.234
   ```
   If HAOS sees ~600 ms too → gateway-side problem. Suspects in order:
   - Bermuda BLE telemetry storm: BLE proxies on .10/.11/.12 broadcasting to HA on .13 saturate inter-VLAN router. Quick test: temporarily disable Bermuda integration for 5 min, observe latency.
   - Firewall ruleset bloat (OPNsense/UDM/etc): spiky cross-rule CPU.
   - mDNS reflector misconfigured (`homeassistant.local` NXDOMAIN suggests this).
2. **Frigate at .13.18** — same-subnet but unreachable. Container down or device offline.
3. **mDNS broken** — `homeassistant.local` returns NXDOMAIN. Avahi/mDNS reflector issue on the network.
4. **Recorder excludes** — once stable, consider excluding `sensor.iphone_*_distance_to_*` (Bermuda chatter) and `sensor.span_panel_*_consumed_energy` (SPAN per-circuit Wh) from history. Biggest writers in current logs.
