# v5.95.0 — Identity fusion: BLE-primary egress producer + face corroboration + producer-outage fail-safe

**Cards:** identity-fusion cycle (D2/D3/D4). Sits under the 6.0.0 IDENTITY-DRIVEN AUTONOMY arc.
**Tier:** 2-DB (1 plan review + 3 framing-disjoint build reviews A/B/D + orchestrator independent mutation-verify + 1 consolidated fix-up). MINOR — new identity-production capability + a new operator-facing fail-safe/drill + guest-naming class.
**Merge:** `feature/identity-fusion-d2d3d4` → develop. D1 (real-time MQTT face bridge) is a follow-on, measure-gated on the Frigate restart.

## Problem (measure-before-build)

Live probes overturned the face-first premise: egress `person_id` attach was **1 of 7,265** — not because face is dead, but because Frigate face is **intermittent** (proven ~135 named recognitions in an 08-30/31 burst, then the service flapped unavailable) and, even when up, faces fire at **interior** cameras while people linger — ~**0%** land within the 45s door-crossing window (~3% even at ±300s). The always-on named crossing signal is **BLE `person.<slug>` home↔away transitions** (~106/14d, Bermuda-sourced for the 3 active residents).

## Solution — extend the existing resolver, don't rebuild

- **D2 — BLE-transition leg** in `transit_validator._resolve_egress_face_identity`: sourced from `person.<slug>` home↔away transitions (both directions), **provenance-guarded** to a Bermuda/BLE `device_tracker` source (token/prefix allowlist — not a substring, so wall tablets can't forge a BLE leg). BLE is the **primary** crossing namer (the transition edge *is* the crossing); face **corroborates** (BLE+face-agree → 0.95 confidence).
- **D3 — known-face-guest class:** `guest:<name>` slug + `CONF_KNOWN_FACE_GUESTS` (options flow). A face-known guest with no BLE (e.g. a semi-frequent visitor) is **named as a guest, not dropped**. Precedence: on BLE(resident)-vs-face disagreement the resolver **abstains for any non-resident face slug** (never attributes a guest's crossing to a resident).
- **D4 — producer-outage fail-safe** (the hard requirement): a single centralized `_face_suppressed_now()` checkpoint that **every** face-emission path routes through (the egress resolver, the raw census identity union, and the presence pre-arrival path), driven by a **registry-resolved `sensor.frigate_status_2` health gate** (fail-closed on configured-but-absent) + a wall-clock staleness drop for silently-frozen faces. A dedicated **drill switch** (`switch.egress_identity_face_failsafe_drill`, RestoreEntity, drill-only, boot-ON raises a repair issue) forces the outage condition on demand for validation with Frigate healthy.

## Reviews

Plan review FIX-REQUIRED (SIGNAL_PERSON_ARRIVING is multi-source incl. camera_face → wrong BLE source; no departure signal; census-union is a live consumer) → re-planned onto `person.<slug>`. 3 framing-disjoint build reviews all FIX-REQUIRED — caught **4 independent fail-safe leaks** (health gate probed a non-existent `binary_sensor.frigate_status_2`; frozen-face; ungated raw census union; ungated presence path) + **2 zero-config attribution bugs** (a guest attributed to a resident; a wall-tablet `"ble"`-substring forging BLE legs). Consolidated fix-up **centralized** suppression across all face paths + closed both attributions. Orchestrator independently mutation-verified: neutering the central checkpoint turns the raw-census, presence, and 4-path-suppression tests RED. 23 cycle tests; full suite at the 63-failing develop baseline (0 net-new).

### Acceptance criteria
- **Verify:** with the drill engaged (Frigate healthy) → zero face-provenance identity attaches on any path; BLE still names residents; a known guest reads anonymous (never misattributed); no pipeline stall; no security-alert downgrade.
- **Verify:** a BLE arrival names the resident; a resident-vs-guest disagreement abstains.
- **Live:** post-restart, `person_id` attach rises from ~0% toward the BLE-transition rate; the drill switch suppresses all face paths and releases cleanly; `sensor.*_persons_in_house` exposes `face_producer_health` + `identified_guests_count`.

## Known residual (carded)
`IDENTITY-FLAPPING-FACE-VETO-1` (Tier-2 fast-follow): the staleness gate (`age(now − last_changed) > TTL`) closes a *silently*-frozen face but not a *flapping*-frozen one (re-stamps `last_changed` → age≈0). Close via a `person not_home` veto backport onto the resolver + a flap/corroboration guard. The producer-*outage* fail-safe (the operator's primary concern) is fully closed + verified.

## Non-goals
D1 real-time MQTT face bridge (measure-gated on Frigate restart), the 6.0.0 consumer cards, the two door-naming cards (door-face-coverage-gated), SECURITY-CENSUS-UNKNOWN-WIRE-1 + LAST-RESIDENT-EGRESS-ARM-1 (parked), Frigate service stability (homelab).

## Pre-deploy gate
Merge clean, no conflict markers, py_compile clean, 23 cycle tests pass; full-suite baseline-diff = 0 net-new (builder-run ×2; orchestrator suite re-runs were killed environmentally, fusion file + load-bearing-checkpoint independently verified). Rollback tag `rollback-pre-5.95.0`.

## Live Validation — post-restart (to record as `Validated <date>`)
- Drill ON (Frigate healthy) → all 4 face paths suppressed; BLE names Oji/Ezinne/Jaya; a guest reads anonymous; release → face resumes.
- `person_id` attach rate vs the 1/7265 baseline.
- Ziri away = expected-silent (not a coverage failure); validates on his return.
