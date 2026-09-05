# PLANNING — BLE crossing producer: device_tracker re-architecture (rev 3)

**Card:** EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1 (pivoted to re-arch)
**Tier:** 3 (delicate, cross-component, invariant-critical — the mission-critical egress-identity producer; wrong attribution = corrupted person_id).
**Rev 3 (reuse-first + BLE-only, operator-directed + measured 2026-09-05):**
- **Source = the resident device_trackers whose `source_type == bluetooth_le`, everything else excluded** (operator: "make the list the same as the device trackers that are ble; exclude the rest"). Derived at RUNTIME (no hardcoded map, no CONF): iterate `_get_tracked_person_slugs()` → each `person.<slug>.attributes["device_trackers"]` → keep only `source_type == bluetooth_le`. This structurally excludes wall tablets / entrypad / Macs (all `gps`) with no allowlist. **The rev-2 hardcoded `EGRESS_CROSSING_TRACKERS` map is DROPPED.**
- **GPS is NOT admitted** — measured BLE-ONLY-SUFFICIENT: BLE trackers fire both directions with 0 unavailable churn; the GPS phone had 355 unavailable flaps / 9 departures and the 2nd GPS phone was silent 14d. So there is ONE provenance class (ble); the rev-2 GPS/BLE window split is DROPPED.
- **NEW mandatory sustain/debounce gate** (measured: bermuda trackers proximity-flap ~2× near the boundary; sustained >30min converges to ~0.7–0.9 real trips/day/resident). A raw edge is trusted as a crossing only if it SUSTAINS for `BLE_CROSSING_SUSTAIN_S` (see D1a).
- **REUSE, do not rebuild** (per the presence-infra inventory): the existing listener machinery (`_register_ble_transition_listeners`/`_on_person_state_change`, re-sourced — NOT a parallel listener), the source_type classifier (`person_coordinator._read_source_inventory`), `_ble_fleet_live`, the `_face_arrival_cooldown` refractory pattern, and the `_resolve_ble_legs` TTL cache. Keep the shared function GENERAL (operator: don't permanently narrow it to BLE).
**Rev 2 (retained):** PLAN-CRIT-1 (unavailable-forges-crossing), per-(slug,direction) single-use, TTL coupling, INV-EGRESS-ID validation, discriminating observability, asymmetric window.
**Supersedes:** the `feature/ble-crossing-tracker-allowlist` approach (person.state + source-allowlist filter).

## Why (root causes)
1. Attach = 1/7314: BLE leg keyed off `person.<slug>` with a Bermuda-only gate; departures are GPS-sourced → every departure rejected.
2. **D-HIGH-1:** `person.state` is a lossy HA aggregate of ALL the person's trackers, resolved by a `last_updated` race (HA `person`; `_get_latest` picks the most-recently-updated GPS tracker). `person.oji_udezue` = 19 trackers incl. 6 stationary GPS Macs that can flip/consume the edge → real crossings later produce no leg.
3. **A-3 (HIGH):** symmetric ±330s window + legs never consumed → one person's departure leg labels ANOTHER's crossing.
4. **D-MED-1:** rejected-leg counter surfaced nowhere → the 1/7314 hid for months.

## Solution — subscribe to the body-phone device_trackers directly
Stop consuming `person.<slug>`. Subscribe to each resident's explicitly-configured body-phone **device_trackers**. A device_tracker edge is the unaggregated signal — no person-component race; stationary devices excluded by not being subscribed.

### Falsifiable invariant (Tier-3)
> For resident R, a crossing leg is recorded **iff** one of R's explicitly-configured body-phone device_trackers makes a **valid** home↔away edge, where **valid** = both old and new state ∈ {`home`, `not_home`, a zone name} (a transition where either side is `unknown`/`unavailable`/`None` is NEVER a crossing). And:
> - (a) **no** non-subscribed device (stationary, another resident's, or an offline-flapping tracker) can produce OR consume R's crossing edge;
> - (b) a real crossing event produces **exactly one** leg per (slug, direction) even when R has multiple trackers firing (dedup/refractory), and that leg attaches to **at most one** crossing (per-(slug,direction) single-use);
> - (c) a leg attaches only in the **direction-correct** window: a departure (exit) leg may only *trail* its crossing; an arrival (entry) leg may only *lead* it;
> - (d) every attached `person_id` is a canonical slug in `tracked_persons` (INV-EGRESS-ID).

Falsified by: a leg from an `unavailable`/`unknown` transition; a leg from a non-subscribed device; ≥2 legs or ≥2 attaches for one real crossing event; an attach out of direction/time; a real single-resident crossing producing no leg when its phone edge fired; an attached slug not in `tracked_persons`.

## Deliverables

### D1 — BLE device_tracker subscription, RUNTIME-DERIVED (replaces the person.state listener)
- **No const map, no CONF.** Build the subscription set at REGISTRATION time by reusing the existing runtime inventory: for each slug in `_get_tracked_person_slugs()` (`camera_census.py:3142`), read `person.<slug>.attributes["device_trackers"]`, and keep each tracker whose `source_type == "bluetooth_le"` (read it exactly as `person_coordinator._read_source_inventory` does, `person_coordinator.py:206-243`). Build the resulting `tracker_id → slug` dict in memory. This yields (live 2026-09-05): oji=`iphone_oji_bermuda_tracker`; ezinne=`ezinne_iphone`,`ezinne_iphone_bermuda_tracker`; jaya=`private_ble_device_249050`,`iphone_jaya_bermuda_tracker`; ziri=`ziri_iphone` (away). GPS/router trackers (wall tablets, Macs, entrypad, the phalanx iPhones) are excluded by the `bluetooth_le` filter.
- **INV-EGRESS-ID:** slugs come from `_get_tracked_person_slugs()` by construction, so they're tracked by definition — still assert it and drop any that aren't, one-time WARNING.
- **Listener:** re-source the EXISTING `_register_ble_transition_listeners` (`camera_census.py:3810`) to `async_track_state_change_event` on the derived tracker ids instead of `person.<slug>`. Reuse its existing idempotent teardown/`_ble_transition_unsubs` machinery — do NOT stand up a parallel listener (double-ingest hazard). Keep the shared function general; re-register on options/person change (the set is now derived from `tracked_persons` + their trackers, so a person/tracker change must re-derive — hook the existing re-register path).
- **Edge handling** (the re-sourced `_on_person_state_change`, now fed device_tracker events — rename to `_on_crossing_tracker_state_change` for clarity):
  - **PLAN-CRIT-1 state-validity gate:** admit ONLY when BOTH old and new state ∈ {`home`, `not_home`, zone-name}. If either is `unknown`/`unavailable`/`None`/`""` → DROP + increment `_ble_edge_dropped_invalid_count`. (Measured: BLE trackers had 0 unavailable churn, but keep the guard — it's the CRIT.)
  - Direction: new==`home` → `arriving`; new is a valid away value → `departing`. slug from the derived map.
  - Provenance is uniformly `ble` (the source filter guarantees it) — no GPS/BLE split, one window class.
- **D1a — sustain/debounce gate (NEW, measured-mandatory).** Bermuda trackers proximity-flap ~2× near the boundary. A raw edge is trusted as a crossing only if it SUSTAINS: on an edge, schedule a confirm after `BLE_CROSSING_SUSTAIN_S` (reuse the `async_call_later` supersession/teardown precedent — cancel the pending confirm if the state reverses before it fires); if the state still holds at confirm, append `BleTransitionLeg(slug, direction, ts=ORIGINAL edge last_changed→UTC-aware, provenance="ble")` (original timestamp preserved so the ±window correlation stays accurate); if it reversed, drop it as flap (+ increment `_ble_edge_flap_dropped_count`). This subsumes the rev-2 per-(slug,direction) refractory: a same-person second tracker firing the same direction within the sustain window collapses to the one confirmed leg. `BLE_CROSSING_SUSTAIN_S` = module knob, default 180 (measured: most bermuda flap reverses well under 5 min; 180s filters it while adding ≤3 min stamp latency — acceptable for identity, not real-time actuation). One-line why on the knob.
- **Acceptance:** a sustained edge on `device_tracker.iphone_oji_bermuda_tracker` appends one leg for `oji_udezue`; a `gps` tracker (e.g. `phalanxiphone15promaxcflare`) or a wall tablet is never subscribed → produces nothing; an edge that reverses within `BLE_CROSSING_SUSTAIN_S` produces no leg (flap dropped+counted); an edge into/out of `unavailable` produces nothing (dropped+counted).

### D2 — A-3 fix: asymmetric window + per-(slug,direction) single-use (site: `_resolve_ble_legs` ONLY; face windows untouched)
- **Asymmetric window** in `_resolve_ble_legs` (`camera_census.py:3803-3808`) — the ONLY site to change; the face window at `transit_validator.py:1343-1349` is NOT touched. Replace the symmetric `-ttl ≤ cross_age ≤ ttl` test with direction-keyed bounds (verify the existing `cross_age` sign against the current symmetric test before wiring):
  - **Departure (exit):** the leg must TRAIL the crossing — admit only `0 ≤ (leg_ts − crossing_ts) ≤ TRAIL`.
  - **Arrival (entry):** the leg must LEAD the crossing — admit only `0 ≤ (crossing_ts − leg_ts) ≤ LEAD`.
  - Bounds (single BLE class — the source filter guarantees all legs are BLE; the rev-2 GPS split is dropped): `BLE_EGRESS_EXIT_TRAIL_S = 90`, `BLE_EGRESS_ENTRY_LEAD_S = 90` (BLE proximity edges land close to the physical crossing). Module rung, one-line why each.
  - **TTL coupling (must-fix):** re-derive `BLE_TRANSITION_CACHE_TTL_S` off the BLE family, not the face family: `BLE_TRANSITION_CACHE_TTL_S = max(BLE_EGRESS_EXIT_TRAIL_S, BLE_EGRESS_ENTRY_LEAD_S, BLE_CROSSING_SUSTAIN_S) + 30`. Add an explicit invariant/comment `TTL ≥ max(all bounds incl sustain)` so a future bound bump can't be silently pruned before its window closes.
- **Per-(slug,direction) single-use:** consumption happens in a census method called from the resolver **after the attach branch commits** (`transit_validator.py:1378-1390`), and ONLY on the attach path — abstain/disagree/no-leg paths must NOT consume. On attach, remove **ALL** legs for that `(slug, direction)` from the cache (not just the one matched) — one real departure may have collapsed to one leg via refractory, but belt-and-suspenders across any residual siblings.
- **Acceptance (discriminating):** A-3 repro — Oji leaves T0 (leg trails his own crossing, attaches oji); Ezinne crosses T+200 with Oji's leg still in cache → Ezinne's crossing does NOT attach `oji_udezue` (Oji's leg PRECEDES her crossing → outside the trailing window, and/or already consumed).

### D3 — discriminating observability (replaces the non-discriminating rejected-count)
- The old `_ble_leg_rejected_provenance_count` provenance gate is GONE (subscription IS the gate); **retire it** (or repurpose to count `_ble_edge_dropped_invalid_count` from the state-validity gate — pick one, document it).
- **Mandatory** discriminating counters, surfaced as attributes on the persons-in-house sensor (alongside `egress_identity_last_attach`): legs produced per direction, attaches, abstains, and `_ble_edge_dropped_invalid_count`. This is the ONLY observable that distinguishes "working" from "dead" post-re-arch (the rejected-count reads 0 either way).
- **Acceptance:** the produced/attached/abstained counters are readable live and a query shows attaches climbing off 1/7314.

## Housekeeping (builder MUST do)
- The five existing tests driving `_on_person_state_change` with synthetic `person.*` events (`quality/tests/test_identity_fusion_d2_d3_d4.py:246,270,658,678,727`): **rewrite in place** to drive the new `_on_tracker_state_change` with `device_tracker.*` events (do not delete — they encode real behaviours). The 4 provenance-allowlist tests from the prior build likewise migrate.
- Fix the now-wrong docstrings/comments: `camera_census.py:220-236` ("a single BLE home↔away transition on `person.<slug>`") and the cache comment at `:1280-1283`.

## Non-goals / parked
- Config-flow exposure of the tracker map (module rung is deliberate — security).
- D-LOW-2 rename brittleness (inherent to explicit ids; the D3 observability catches it).
- Face/D1 sub_label bridge (separate card; face path untouched here; the same asymmetric+single-use fixes will benefit it later).
- Ziri redundancy (`iphone_ziri_bermuda_tracker` exists but not in `person.ziri` — config gap, note only; Ziri away for months).

## Tier-3 review framings (framing-disjoint, parallel)
- **A — local correctness:** map→slug, direction derivation, source_type classification + fallback, refractory dedup, leg append; every resident produces both directions where their trackers allow.
- **B — integration/lifecycle:** listener register/teardown (no leak, no double-subscribe), restart, the asymmetric-window + single-use interacting with the shared face-leg path (face attribution NOT regressed), D4 fail-safe still orthogonal, TTL≥max(bounds) holds.
- **C — test authority (per-site source mutation):** RED-on-neuter for each of {subscription admits a valid edge, unavailable-edge dropped, stationary/non-subscribed rejected, refractory dedup, asymmetric window, per-slug single-use}.
- **D — adversarial completeness:** falsify the invariant across the whole surface — unavailable-forge, non-subscribed produce/consume, double-attach, silent-drop of a real crossing, out-of-`tracked_persons` slug. Legal-config repros required.

## Acceptance criteria (cycle)
- **Test:** the D1/D2/D3 anchors, each RED-on-neuter.
- **Live:** on the next real resident departure/arrival, `person_entry_exit_events` gets a row with the correct `person_id`; the produced/attached counters move; `_ble_edge_dropped_invalid_count` catches any offline flaps.
- **Live (discriminating):** a departure attaches the departer's slug, NOT a co-present other resident's (A-3 closed); an `unavailable` flap on a phone produces no crossing (PLAN-CRIT-1 closed).
