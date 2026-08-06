# v5.55.0 — Exterior Cycle 2: Deep-Night Vehicles, Fused Sourcing, Seam Telemetry

Operator GO 2026-08-06 on the cycle-1 riders.

- **Deep-night vehicle signal (operator concept):** a vehicle track
  opening 22:00-06:00 house-local while house ∈ {away, sleep, vacation}
  pages HIGH under its OWN hazard (`exterior_vehicle` — minted so NM
  dedup/boot-settle can never cross-throttle person alerts) with the
  path narrative; ONE page per track (first-alert-per-track bounds the
  parked-car storm from ~96/night to 1). Daytime/occupied vehicles are
  digest-only. Accepted residual (documented): family arriving ~23:30
  while still `away` = one HIGH page, treated as arrival confirmation.
  Kill: linker fire axe or TRACK_LINK_WINDOW_S=0 mutes the emitter.
- **Fused dual-host sourcing (F1-retirement insurance):** perimeter
  person/vehicle/animal handlers subscribe to base AND `_2` siblings
  (registry-derived, EVENT_HOMEASSISTANT_STARTED re-scan, WARN when
  missing); cooldown+in-flight keys collapse to the camera so one
  physical event = one alert from either host; snapshot resolver strips
  `_2` so F2-sourced alerts keep Frigate snapshots with zero delay.
- **Seam-split telemetry:** per-seam missed-intermediate candidates
  counted (2-graph-hop opens within the link window), surfaced on the
  diagnostic sensor (since-boot; capped 64 seams). Evidence feed for the
  camera-tuning loop; never changes edges.
- **Animal ingress:** linker/census/episodes only, no NM path (top
  animal camera ~6/day; the daily-cap knob was deleted until an alert
  path exists — parsimony).
- **Amcrest alias:** `armcrestpooloverhead`→`armcrest` verified against
  the live registry.
- **Dashboard:** exterior-activity + badge cards staged in
  docs/dashboards/ura_v8_exterior_cycle2_cards.md (apply post-deploy;
  reported doorbell duplicate NOT found in current v8 — needs operator
  confirm).

Reviews: 4 framing-disjoint (A/B/C/D) — 6 HIGHs all fixed (hazard mint,
in-flight race ×2 reviewers, snapshot `_2` strip, legacy mislabel, 2
test-authority gaps) + 12 MED/LOW fixed in-cycle. NM bucketing verified:
dedup/boot-settle now partition by hazard; channel token buckets remain
shared by design (pre-existing; bounded by first-alert-per-track;
promotion path documented). Orchestrator pass found TWO more
silently-green sites post-fix-up (in-flight guard, hazard kwarg) — both
anchored red/green personally. #62 ledger +2.

## Live Validation (prospective)
- **Live:** switches/census unchanged from v5.53.0; zero URA ERROR lines.
- **Live:** first deep-night vehicle while away/sleep → ONE HIGH page
  with narrative under hazard exterior_vehicle; daytime vehicles silent.
- **Live:** seam_split_candidates attr present (empty until organic).
- **Live:** WARN inventory at boot for cameras missing `_2` siblings
  matches the known F2 coverage.

## Validated 2026-08-06 post-restart
v5.55.0 live on HA; zero URA ERROR lines; both switches ON, census sensors present (0), house cycled arriving normally. Organic criteria
(first egress event legs / first deep-night vehicle, seam counters)
ride the next natural events — morning sweep checks.
