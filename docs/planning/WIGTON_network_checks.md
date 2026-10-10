# Wigton — network-layer checks (for the homelab agent)

## Context
- **Wigton** = second home. Home Assistant OS box at **192.168.17.243** (HA web on **port 80**, Observer on 4357, Advanced SSH add-on on 22). Gateway **UDM Pro** at 192.168.17.1 (also `alarm_control_panel.wigton_udmp_alarm_manager`).
- **Main house** (Madrone) clients reach Wigton across sites: the client used for all tests below is the Mac mini at **192.168.13.149**, default gateway **192.168.13.1**. Route to 192.168.17.0/24 is via that gateway (site-to-site path — confirm what it is: UniFi Site Magic / WireGuard / IPsec / Teleport).
- Wigton also runs **cloudflared** (Cloudflare tunnel add-on) — the phone app may use that path rather than the LAN or the site-to-site link.

## What was observed (2026-10-10, all times UTC)
1. **Connections from 192.168.13.149 to 192.168.17.243 intermittently time out for minutes**, while other ports/hosts on the same path are reachable at the same moment:
   - ~00:00 (10-10 00:00 CDT = 05:00 UTC; first noticed), ~13:40, 14:18–14:45 (brief recovery 14:36), 15:18–15:20, 15:31–15:32, ~15:58–16:05.
   - 14:29: TCP **80 refused/closed**, **4357 open**, gateway 192.168.17.1:443 open.
   - 15:19 and 15:32: TCP **22 timed out**, **80 open**, 4357 open, gateway open; other internet/local hosts fine from the Mac.
   - 16:0x: SSH failed at **kex/banner exchange** (TCP connected, then no data) — packets dropped mid-session, not just at SYN.
2. **The target host was healthy throughout:**
   - HA container up 17 h, host up 5 days, load < 1, ~9 GB RAM free, no kernel link up/down, no OOM.
   - A watcher running **on the box** (curl to 127.0.0.1 every 5 s) logged 245 consecutive 200s at 1–3 ms from 15:40–16:00, including the 15:58+ window when the Mac could not connect.
   - The SSH add-on's own log shows **no connection attempts arriving** during the 15:31–15:32 failures — the SYNs never reached it.
3. **Pattern:** failures correlate with bursts of client traffic (many API/websocket calls, history pulls, options-flow reads) and then clear on their own after 2–8 minutes. Different destination ports fail independently.
4. **Separately**, the operator (remote) and **Omonele (local at Wigton)** both reported Home Assistant "stalling" at overlapping times. Not yet proven to be the same mechanism — the on-box watcher has not yet captured a stall while they reported one. Treat the local stalls as a second question (check 6).

## Checks to run (please report each as found / not found, with evidence)

1. **UDM Pro (Wigton) threat management / IPS**
   - Is IDS/IPS (CyberSecure / Threat Management) enabled? Detection-only or blocking?
   - Any events with source 192.168.13.149 (or 192.168.13.0/24) → 192.168.17.243 in the windows above? Signature names?
   - Any auto-block / "suspicious activity" quarantine of 192.168.13.149 or the site-to-site peer?
2. **Main-house gateway (192.168.13.1) IPS** — same questions for traffic leaving towards 192.168.17.0/24.
3. **Site-to-site link health** — what technology; tunnel up/down/rekey events, packet loss or MTU/fragmentation issues in those windows. Check for MSS clamping/MTU mismatch (SSH failing at kex/banner exchange with TCP established is a classic MTU black-hole symptom).
4. **Firewall / traffic rules**
   - Any rate limits, connection limits, or per-source caps on inter-site traffic or on the HA box (port 80/22)?
   - Any "block after N connections" style rules, geo/threat lists, or Ad-blocking/DNS shields that could interfere.
   - Conntrack / session table exhaustion on either gateway (counts near limit at those times?).
5. **HA box switch port / Wi-Fi**
   - Is 192.168.17.243 wired? Which switch/port? Port errors, flaps, PoE events, STP changes, storm-control actions in those windows.
   - If Wi-Fi: AP roaming/disconnect events for its MAC.
   - IP conflicts: any other device claiming 192.168.17.243 (ARP/DHCP logs)?
6. **Local stalls seen by Omonele (Wigton LAN)**
   - At the times she reported (operator to supply exact times), any UDM/switch/AP events affecting her device or the HA box?
   - Which path does the Home Assistant app use on her phone at home: LAN IP, `homeassistant.local`, Nabu Casa, or the Cloudflare tunnel hostname? Any cloudflared tunnel disconnects in those windows (cloudflared add-on log)?
   - mDNS/IGMP issues (multicast flooding, IGMP snooping changes) at those times.
7. **DNS** — does anything resolve Wigton's HA hostname to a different address intermittently?

## Useful facts for correlation
- HA local watcher log: `/tmp/hawatch.log` on the Wigton SSH add-on (`ssh wigtonhaos@192.168.17.243`; restarts of the add-on wipe it). Format: `UTC-time HTTP-code seconds`.
- HA core log via SSH: `sudo docker logs --since 24h homeassistant`.
- Profiler asyncio debug is ON at Wigton (slow event-loop callbacks are logged) to catch a real HA freeze if one happens.

## Desired outcome
A yes/no answer for: (a) is something on the network path dropping/blocking the main-house client's traffic to 192.168.17.243, and what rule/feature; (b) is there any network event matching the local stalls Omonele saw. Plus the change recommended (e.g., allow-list 192.168.13.0/24 ↔ 192.168.17.243 in IPS, fix MTU/MSS on the tunnel).
