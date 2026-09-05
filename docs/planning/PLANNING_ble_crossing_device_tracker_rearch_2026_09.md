# PLANNING — BLE crossing producer: device_tracker re-architecture

**Card:** EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1 (pivoted to re-arch)
**Tier:** 3 (delicate, cross-component, invariant-critical — the mission-critical egress-identity producer; wrong attribution = corrupted person_id).
**Supersedes:** the `feature/ble-crossing-tracker-allowlist` approach (person.state + source-allowlist filter). Build on top of that branch (reuse the reviewed allowlist constant + tests); replace the listener source.

## Why (root causes from the v5.95.0 attach=0 investigation + 2 reviews)
1. **Attach = 1/7314** because the BLE leg producer keyed off `person.<slug>` transitions with a Bermuda-only provenance gate, and departures are GPS-sourced → every departure rejected (original defect).
2. **D-HIGH-1:** `person.state` is a **lossy HA aggregate** of ALL the person's device_trackers, resolved by a `last_updated` race (HA `person` integration; `_get_latest` picks the most-recently-updated GPS tracker ignoring only unknown/unavailable). `person.oji_udezue` has 19 trackers incl. 6 stationary Macs that are GPS+home — a stray Mac update can flip and **consume** the crossing edge, so a real crossing later produces no leg. Keying off `person.state` is therefore a race, not a signal.
3. **A-3 (HIGH):** symmetric ±330s window + legs never consumed → one person's departure leg can attach to ANOTHER person's crossing (wrong `person_id` — worse than none).
4. **D-MED-1:** the rejected-leg counter is surfaced nowhere — which is why "every departure dropped" hid for months.

## Solution — subscribe to the body-phone device_trackers directly
Stop consuming `person.<slug>`. Register state-change listeners on each resident's explicitly-configured **body-phone device_trackers** (the reviewed allowlist, now a tracker→slug map). A `device_tracker` state edge is the *unaggregated* signal — no person-component race, and stationary devices are excluded by simply not being subscribed.

### Falsifiable invariant (Tier-3 — D's job is to break exactly this)
> A crossing leg for resident R is recorded **iff** one of R's explicitly-configured body-phone device_trackers changes `home`↔(`not_home`/away); (a) no stationary device and no other resident's device can produce OR consume R's crossing edge; (b) a recorded leg attaches to **at most one** crossing (single-use); (c) a leg attaches only within the **direction-correct** time window (a GPS departure leg may only *trail* the crossing; an arrival leg may only *lead* it).

Falsified by: any reachable path where a non-subscribed device produces/consumes a leg; a leg attaches to ≥2 crossings; a leg attaches out of direction/time; or a real single-resident crossing produces no leg when its phone edge fired.

## Deliverables

### D1 — tracker→slug subscription (replaces person.state listener)
- Convert `EGRESS_CROSSING_ADMISSIBLE_TRACKERS` (flat frozenset) into a **tracker→slug map** `EGRESS_CROSSING_TRACKERS: Final[dict[str,str]]` in `const.py` (module rung; security-relevant; "requires code review to change"). Contents (operator-confirmed, iPhones + BLE only; iPad + samsung EXCLUDED):
  - `device_tracker.phalanxiphone15promax` → `oji_udezue`
  - `device_tracker.phalanxiphone15promaxcflare` → `oji_udezue`
  - `device_tracker.iphone_oji_bermuda_tracker` → `oji_udezue`
  - `device_tracker.ezinne_iphone` → `ezinne`
  - `device_tracker.ezinne_iphone_bermuda_tracker` → `ezinne`
  - `device_tracker.jjs_iphone` → `jaya`
  - `device_tracker.private_ble_device_249050` → `jaya`
  - `device_tracker.iphone_jaya_bermuda_tracker` → `jaya`
  - `device_tracker.ziri_iphone` → `ziri`
- Replace `_register_ble_transition_listeners` to `async_track_state_change_event` on the map's keys (not `person.*`). On an edge, derive `slug` from the map, direction from the device_tracker state transition: `home`→(not-home) = `departing`; (not-home)→`home` = `arriving`. (device_tracker states: `home` / `not_home` / a zone name. Treat any non-`home` as away for the edge.)
- Keep `BleTransitionLeg` shape; set `provenance` to distinguish `ble` (BLE tracker) vs `gps` (iPhone GPS tracker) using the tracker's `source_type` (or the entity's known class) — needed by D3.
- **Acceptance:** an edge on `device_tracker.phalanxiphone15promaxcflare` appends a `departing` leg for `oji_udezue`; a stationary Mac update produces nothing (not subscribed).

### D2 — A-3 fix: asymmetric window + single-use consumption
- **Asymmetric window** in `_resolve_ble_legs` / the resolver's exit-vs-entry matching: a departure (`exit`) leg may only *trail* the crossing (leg_ts ≥ crossing_ts, up to a bound); an arrival (`entry`) leg may only *lead* it. Replace the symmetric ±`BLE_TRANSITION_CACHE_TTL_S` test. Name the bounds (`BLE_EGRESS_EXIT_TRAIL_S`, `BLE_EGRESS_ENTRY_LEAD_S`) as module constants.
- **Single-use legs:** once a leg produces an attach, remove it from the cache so it cannot label a second crossing.
- **Acceptance:** the A-3 repro (Oji leaves T0, leg stamped T+120; Ezinne crosses T+200) → Ezinne's crossing does NOT attach `oji_udezue` (leg precedes her crossing → out of the trailing window; and/or already consumed).

### D3 — D-MED-1 observability + D-MED-2 window discrimination
- Surface `_ble_leg_rejected_provenance_count` **and** the last rejected `source` as attributes on the persons-in-house sensor (alongside `egress_identity_last_attach`). Add a per-direction attach/miss count if cheap.
- **D-MED-2:** GPS-sourced legs get a *tighter* trailing bound than BLE-sourced (GPS geofence lags/flaps ~100m); discriminate by `BleTransitionLeg.provenance`/`source_entity`. Name the GPS bound separately.
- **Acceptance:** the rejected-count is readable live; a query shows attach-rate climbing off 1/7314 post-deploy.

## Non-goals / parked
- Config-flow exposure of the tracker map (module rung is deliberate — security).
- D-LOW-2 rename brittleness (inherent to explicit ids; observability from D3 catches it).
- Face/D1 sub_label bridge (separate card; this re-arch does NOT touch the face path, but the same asymmetric-window + single-use fixes will benefit it later).
- Ziri redundancy (only `ziri_iphone`; `iphone_ziri_bermuda_tracker` exists but isn't in `person.ziri` — config gap, note only; Ziri is away for months).

## Tier-3 review framings (framing-disjoint, run in parallel)
- **A — local correctness:** the tracker→slug map, direction derivation, leg append; every resident can produce both directions; source_type→provenance classification correct.
- **B — integration/lifecycle:** listener registration/teardown on setup/reload (no leak; no double-subscribe), restart resilience, the asymmetric-window + single-use interacting with the existing face-leg path (no regression to face attribution), D4 fail-safe still orthogonal.
- **D — adversarial completeness:** falsify the invariant across the whole surface — can any non-subscribed device produce/consume a leg? can a leg double-attach? can a real crossing be silently dropped (the D-HIGH-1 class — is it actually gone)? legal-config repros required.
- **C (test authority):** per-site source mutation — each of {subscription admits, stationary rejected by non-subscription, asymmetric window, single-use consumption} has a RED-on-neuter test driving real code.

## Acceptance criteria (cycle)
- **Test:** the D1/D2/D3 anchors above, each RED-on-neuter.
- **Live:** post-deploy, on the next real resident departure/arrival, `person_entry_exit_events` gets a row with the correct `person_id`; `_ble_leg_rejected_provenance_count` stops incrementing on real phone edges; the observability attribute is readable.
- **Live (discriminating):** a departure attaches the departer's slug, NOT a co-present other resident's (A-3 closed).
