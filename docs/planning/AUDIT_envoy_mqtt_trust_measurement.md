# AUDIT — Envoy MQTT stream trust measurement (ENVOY-STREAM-TRUST-MEASURE-1)

Criteria: `PLANNING_envoy_local_witness_and_solar_follow.md` §3.1-3.7, plus §3.8 (partial fleet,
added 2026-09-25 after the operator-initiated Envoy reboot).
Probe (read-only, rerunnable): `scripts/probes/envoy_stream_trust_probe.py`
`ssh ha "python3 - START END [XSTART-XEND ...]" < scripts/probes/envoy_stream_trust_probe.py` (UTC epochs).

## Run 1 — PRELIMINARY (2026-09-25 21:00 CDT)

Window 16:40 → 21:00 CDT (4.3 h), **excluding 18:21 → 20:15** (HA core 2026.9.2→.3, Envoy reboot,
core-switch + UDM restart). Clean data: **2.4 h**. This is NOT the ≥24 h window the plan requires;
it is run now because the operator asked for it and because several criteria already resolve.

| # | Criterion | Measured | Verdict |
|---|---|---|---|
| 3.1 | Freshness | data_age time-weighted p50 20 s, p95 23 s, max 39 s; 0 s above 60 s. Envoy payload refresh p50 1 s, p95 1 s, max 224 s. Stream unavailable 4 episodes / 18 s total (longest 17 s, pre-reboot). | **PASS** (skew-adjusted). The plan's "p95 ≤ 10 s" is unmeetable as written because of the constant ~20 s Envoy clock skew; skew-adjusted p95 = 3 s. Rule should read "p95 ≤ skew + 10 s". |
| 3.2 | Independence | Native integration unavailable 8,243 s = **93.9 %** of the clean window (5 episodes, longest 2,714 s). Stream also down during only 18 s of that → **stream up 99.78 %** of native-down time. | **PASS (prelim)** — strongest result, and the whole value proposition. |
| 3.3a | enc_agg_soc vs soc_top_level | n=88, identical every sample (0 divergence). | **Redundant** in this window (plan Q1: candidate to drop `soc_top_level` once 24 h confirms). |
| 3.3b | stream vs native | n=0 — native was dead for all overlapping time. | **UNTESTED** — needs native back. Gates the SOC tier. |
| 3.3c | stream vs cloud (cloud ≤ 600 s old) | n=23, mean −1.5 pp, p95 \|d\| 2.9 pp. | Consistent with cloud lag; not a pass criterion. |
| 3.3d | stream SOC vs integrated battery power (added) | 18:30→21:00 integrated discharge 17.8 kWh + 21 min unmeasured gap (~3 kWh at the observed ~9 kW) ≈ 21 kWh vs stream battery_energy drop 35.8 → 11.1 = 24.7 kWh. | **Corroborates** the post-reboot stream SOC (~27 % at 21:00) against a second field. The cloud (frozen at 94.9 since 18:27) is the stale one. |
| 3.4 | Cloud cadence | Value-change row gaps n=7: p50 669 s, p95 1,725 s; 57 % of gaps exceed the 600 s tier bound. Frozen ≥ 2.5 h since 18:27. | **FINDING:** the cloud tier structurally cannot meet its own 600 s bound. |
| 3.5 | Self-consistency | pv + grid + battery − load, n=1,843 (load ≥ 500 W): p50 0.00 %, p95 0.02 %, max 0.4 %. | **PASS.** |
| 3.6 | Contention | Native down-events/day: 09-18 110 · 09-19 162 · 09-20 134 · 09-21 140 · 09-22 163 · 09-23 109 · 09-24 120 · 09-25 51 (native dead from 18:21). | **PENDING** — 09-25 is confounded by the reboot and the native outage. Needs one full post-add-on day. No sign of a rise so far. |
| 3.7 | Reserve witness | Stream backup_reserve 10 = cloud reserve 10.0 (static agreement). No real reserve change in the clean window. | **UNTESTED** — resolves organically: the EC changes the reserve 6-10×/day (overnight 8-9 %, midday 80-99 %, 16:00 → 10 %). |
| 3.8 | Partial fleet | 0 non-physical SOC jumps (> 2 pp/min) in the clean window. During the excluded reboot window: device count 0→48→8, battery_energy fell in ~4.1 kWh per-unit steps, SOC read 87→20 with the battery really at ~90 %. | Failure mode **confirmed real** (reboot-triggered); guard remains a mandatory SOC-tier constraint. |

### What this clears for other builds
- **SOLAR-FOLLOW B1** (stream as solar-follow grid fallback): already shipped; 3.1 + 3.5 PASS confirm it.
  B2/B3 were dropped by the operator.
- **ENVOY-STREAM-SOC-TIER-1** needs 3.1, 3.2, 3.3, 3.5, 3.7. **Cleared: 3.1, 3.2 (prelim), 3.5.**
  **Still open: 3.3b** (needs the native integration up alongside the stream) and **3.7** (needs one
  real reserve change) — both resolve inside the next 24 h window without any action from us, *if*
  the native integration recovers.

### Live observation worth acting on
At 21:00 the Energy Coordinator is **blind**: native tier dead since 18:21, cloud frozen since
18:27, lkg aged out. The stream shows the battery really at ~27 % and discharging ~10 kW into
off-peak. Blind-hold is designed behaviour (EC manual §2.5), but it means the EC cannot make its
usual overnight reserve decisions until a tier comes back — the concrete cost the SOC-tier card exists
to remove.

## Run 2 — FINAL (pending)
Rerun at ≥ 2026-09-26 20:15 CDT with START = 2026-09-25 20:15 CDT (01:15Z, epoch 1790385300) — i.e.
a 24 h window entirely after tonight's restarts — plus exclusions for any further restart (the HAOS
18.3 update is still pending).
