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

## Run 2 — FINAL (2026-09-27 02:02 CDT, overnight pass)

**Window:** 2026-09-25 20:15 → 2026-09-27 02:02 CDT (29.8 h), minus two HA core restarts that landed
inside it (09-26 12:50 and 15:19 — `recorder_runs` 1138/1139), excluded as 12:45–13:15 and
15:12–15:45. **28.7 h clean.** HAOS 18.3 still not applied (host uptime 12 d).
Command: `ssh ha "python3 - 1790385300 1790492529 1790444709-1790446509 1790453529-1790455509" < scripts/probes/envoy_stream_trust_probe.py`

**Probe bug found and fixed before trusting 3.7.** Run 2's first pass reported 8 of 10 reserve changes
as "stream NOT converged". That was the probe: it only looked for a stream match *after* the cloud
change, but the stream reads the Envoy directly and changes **first**. Fixed to match either direction
within ±300 s (`REL_WIN_S`), nearest wins. Raw recorder rows confirm the corrected reading.

| # | Criterion | Result | Verdict |
|---|---|---|---|
| 3.1 | Freshness | age p50 22 s / p95 24 s / max 56 s, 0 s over 60 s; skew-adjusted p95 **4 s** | **PASS** (skew-adjusted rule) |
| 3.2 | Independence | stream up **98.65 %** of 20,552 s native-down time | **PASS on transport** — see note |
| 3.3a | Internal (enc_agg vs top-level SOC) | identical every sample | PASS (redundant fields) |
| 3.3b | Stream vs native SOC | n=1,382, mean −0.00 pp, p95 1.0 pp, max 1.0 | **PASS** |
| 3.3c | Stream vs cloud | mean −2.8 pp, p95 25 pp | cloud is the laggard (3.4), not the stream |
| 3.4 | Cloud cadence | value-change gaps p50 **947 s**, p95 3,225 s; 72 % exceed its 600 s tier bound | cloud tier bound is fiction |
| 3.5 | Self-consistency | p95 residual 0.03 % | **PASS** |
| 3.6 | Contention | native down-events/day: 09-19..24 = 109–163; 09-25 = 52; **09-26 = 15** | **no harm; big drop, CONFOUNDED** |
| 3.7 | Reserve witness | 10/10 cloud changes matched; stream **led** by 1–32 s on 9, lagged 1 s on 1 | **PASS** |
| 3.8 | Partial fleet | 2 non-physical SOC jumps, both one event (below) | **HAZARD — consumer must gate** |

**3.2 note.** The literal rule (≥ 99 %) misses by 0.35 pp, and all of the shortfall is **one** 277 s
episode (09-26 23:09:35–23:14:11) where the stream dropped *together with* native. Microinverter count
then climbed 0 → 4 → 16 → … → 32 over two minutes: the **Envoy itself re-enumerated** (rebooted), the
same signature as the operator's 09-25 reboot. So this was the source going down, not the transport.
No transport can survive that. On transport independence, the stream passes.

**3.8 hazard (the real finding of Run 2).** When the Envoy came back at 23:14:11 the stream published
**SOC = 0** and **backup_reserve = 0, then 30**, then the true values (SOC 36, reserve 10) 36 s later.
A consumer that trusted the first post-reconnect frame would have seen an empty battery. This is the
second live instance of the partial-fleet failure (first: 09-25 reboot, SOC 87 → 20). It turns
ENVOY-STREAM-SOC-TIER-1's device-completeness constraint from a precaution into a **required gate**:
reject stream SOC/reserve until device count is back at fleet size (or a settle window passes after
`unavailable` → value), and never accept a 0 that follows `unavailable`.

**3.6 note.** Native flapping fell from 109–163 down-events a day to 15 on 09-26, the first full day
after the operator's 09-25 Envoy reboot + network-stack restart + core 2026.9.3 — and after the add-on
went live. Four changes on one evening, so we cannot say which one did it. What we *can* say: adding the
stream did not make contention worse. This bears directly on ENVOY-FLAKINESS-181243-1.

### Gate verdict
- **ENVOY-STREAM-SOC-TIER-1: CLEARED to plan**, with one binding constraint from 3.8 (post-reconnect
  junk gate). Every criterion it needed (3.1, 3.2, 3.3, 3.5, 3.7) now has a number.
- **3.1 rule should be restated** as "skew-adjusted p95 ≤ 10 s" (the raw ≤ 10 s is unmeetable given the
  ~20 s Envoy clock skew). Cadence note: Run 2 measures `meters.last_update` deltas at p50 1 s, which
  differs from Run 1's hand sample (~5–6 s). Not resolved here; it doesn't change any verdict.

<details><summary>Raw probe output (Run 2, corrected)</summary>

```
WINDOW 09-25 20:15:00 -> 09-27 02:02:09 CDT  (29.8 h)
  EXCLUDED 09-26 12:45:09 -> 09-26 13:15:09  (30 min)
  EXCLUDED 09-26 15:12:09 -> 09-26 15:45:09  (33 min)
  clean seconds: 103449 (28.7 h)

== 3.1 FRESHNESS (data_age, seconds; includes the constant ~20 s Envoy clock skew)
  time-weighted p50 22  p95 24  max 56  | seconds with age>60: 0
  PASS rule (p95<=10 s) is UNMEETABLE as written: skew floor ~20 s. Skew-adjusted p95 = 4 s
  Envoy payload refresh cadence (distinct meters.last_update deltas): n=101652 p50 1s p95 1s max 337s
  stream unavailable episodes: 1, total 277s, longest 277s
     09-26 23:09:35 -> 09-26 23:14:11  277s

== 3.2 INDEPENDENCE (stream availability while the native integration is unavailable)
  native unavailable: 20552s (19.9% of clean window)
  stream ALSO unavailable during those: 277s -> stream up 98.65% of native-down time   (PASS >= 99%)
  native-down episodes: 18; longest 3124s

== 3.3 AGREEMENT (60 s samples)
  stream enc_agg_soc - soc_top_level     n= 1720 mean  +0.00pp  p50|d| 0.0  p95|d| 0.0  max|d| 0.0  nonzero 0.0%
  stream - native (both available)       n= 1382 mean  -0.00pp  p50|d| 0.0  p95|d| 1.0  max|d| 1.0  nonzero 8.3%
  stream - cloud (cloud <=600 s old)     n=  776 mean  -2.81pp  p50|d| 1.9  p95|d| 25.2  max|d| 65.2  nonzero 94.1%
  PASS rule: |stream - native| <= 2 pp at p95 and |mean| small (no systematic offset)

== 3.4 CLOUD CADENCE (row gaps for overall_charge; value-change rows only)
  n=88 p50 947s p95 3225s max 11222s  (cloud tier bound 600 s; >600 = 72% of gaps)

== 3.5 SELF-CONSISTENCY  residual = pv + grid + battery - load
  n=42772 (load>=500 W) p50 0.00%  p95 0.03%  max 2.0%   (PASS p95 < 2%)

== 3.6 CONTENTION (native battery -> unavailable transitions per local day; recorder keeps 7 d)
  09-19:  122 down-events
  09-20:  134 down-events
  09-21:  140 down-events
  09-22:  163 down-events
  09-23:  109 down-events
  09-24:  120 down-events
  09-25:   52 down-events
  09-26:   15 down-events
  09-27:    4 down-events
  baseline (pre-add-on, ALL state changes/2 ~= down-events): 09-18 ~110, 09-19 ~162, 09-20 ~112; add-on live 09-25 ~16:10

== 3.7 RESERVE WITNESS
  stream backup_reserve now 10; cloud reserve now 10.0
  cloud reserve changes in window: 10; stream changes: 13
     cloud -> 8.0 at 09-26 04:40:33; stream matched at 09-26 04:40:17 (lag -17s)
     cloud -> 10.0 at 09-26 10:25:53; stream matched at 09-26 10:25:45 (lag -8s)
     cloud -> 71.0 at 09-26 14:00:37; stream matched at 09-26 14:00:22 (lag -15s)
     cloud -> 75.0 at 09-26 14:14:10; stream matched at 09-26 14:13:47 (lag -23s)
     cloud -> 78.0 at 09-26 14:33:47; stream matched at 09-26 14:33:46 (lag -2s)
     cloud -> 80.0 at 09-26 14:43:51; stream matched at 09-26 14:43:52 (lag +1s)
     cloud -> 82.0 at 09-26 15:04:18; stream matched at 09-26 15:03:46 (lag -32s)
     cloud -> 84.0 at 09-26 15:52:24; stream matched at 09-26 15:52:21 (lag -3s)
     cloud -> 93.0 at 09-26 15:57:23; stream matched at 09-26 15:57:22 (lag -1s)
     cloud -> 10.0 at 09-26 16:00:15; stream matched at 09-26 16:00:14 (lag -1s)

== 3.8 PARTIAL FLEET (stream SOC slew > 2.0 pp/min = non-physical)
  non-physical SOC jumps: 2
     09-26 23:14:11  38 -> 0
     09-26 23:14:47  0 -> 36
  device-count max 48; time below max 98.5% of 28.7 h
```
</details>
